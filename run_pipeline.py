import yaml
import requests
import subprocess
import time
import re
import os
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# ============================================================
# MODEL CALL
# ============================================================

def run_model(model, prompt, system_prompt=""):
    print(f"\n[DEBUG] Calling model: {model}")

    full_prompt = f"{system_prompt}\n\n{prompt}"

    response = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        },
    )

    response.raise_for_status()
    return response.json()["response"]


# ============================================================
# CODE EXTRACTION (ROBUST)
# ============================================================

def extract_code(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[-1].strip()

    if "print(" in text or "import " in text or "open(" in text:
        return text.strip()

    return None


# ============================================================
# EXECUTOR
# ============================================================

def run_python(code):
    filename = os.path.join(os.getcwd(), f"generated_{int(time.time())}.py")

    print("\n[EXECUTOR] Saving generated code...")

    with open(filename, "w") as f:
        f.write(code)

    print(f"[EXECUTOR] Saved to {filename}")
    print(f"[EXECUTOR] Code length: {len(code)} characters")

    try:
        result = subprocess.run(
            ["python3", filename],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.stdout + result.stderr
    except Exception as e:
        return str(e)


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):
    time.sleep(1)
    with open("project_state.yaml", "w") as f:
        yaml.dump(state, f, sort_keys=False)


# ============================================================
# MAIN LOOP
# ============================================================

print("\n--- META AGENT SERVICE STARTED ---\n")

while True:

    print("\n--- META AGENT CYCLE ---\n")
    print("[DEBUG] Loading YAML files")

    with open("supervisor.yaml", "r") as f:
        supervisor = yaml.safe_load(f)

    with open("coder.yaml", "r") as f:
        coder = yaml.safe_load(f)

    with open("project_state.yaml", "r") as f:
        state = yaml.safe_load(f)

    supervisor_model = supervisor["model"]
    coder_model = coder["model"]

    supervisor_system = supervisor.get("system_prompt", "")
    coder_system = coder.get("system_prompt", "")

    tasks = state.get("tasks", [])

    current_task = None

    for task in tasks:
        if task.get("status") == "pending":
            current_task = task
            break

    if not current_task:
        print("[META] No pending tasks. Sleeping...")
        time.sleep(20)
        continue

    user_goal = current_task["goal"]

    print("\n[DEBUG] CURRENT TASK:", current_task["id"])
    print("[DEBUG] TASK GOAL:\n", user_goal)

    # ========================================================
    # ARCHITECTURAL GUARD
    # ========================================================

    if "runner" in user_goal.lower() or "framework" in user_goal.lower():
        print("[SUPERVISOR] Architectural change detected. Skipping task.")
        current_task["status"] = "skipped"
        save_state(state)
        continue

    # ========================================================
    # SUPERVISOR STEP
    # ========================================================

    print("\nRunning supervisor...\n")

    supervisor_output = run_model(
        supervisor_model,
        user_goal,
        supervisor_system,
    )

    print("\nSupervisor says:\n")
    print(supervisor_output)

    if "ARCHITECT_REQUIRED" in supervisor_output:
        print("[SUPERVISOR] Architect required. Skipping task.")
        current_task["status"] = "skipped"
        save_state(state)
        continue

    # ========================================================
    # CODER STEP
    # ========================================================

    print("\nRunning coder agent...\n")

    coder_output = run_model(
        coder_model,
        supervisor_output,
        coder_system,
    )

    print("\nCoder output:\n")
    print(coder_output)

    # ========================================================
    # EXECUTOR STEP
    # ========================================================

    code = extract_code(coder_output)

    if code:
        execution_result = run_python(code)

        print("\nExecution result:\n")
        print(execution_result)

        # ====================================================
        # FEEDBACK LOOP
        # ====================================================

        feedback_prompt = f"""
You are the supervisor reviewing execution results.

Original Goal:
{user_goal}

Coder Output:
{coder_output}

Execution Result:
{execution_result}

Reply with ONLY ONE LINE.

COMPLETE
or
IMPROVE: <short instruction>
"""

        review = run_model(
            supervisor_model,
            feedback_prompt,
            supervisor_system,
        )

        print("\nSupervisor review:\n")
        print(review)

        if "COMPLETE" in review.upper():
            current_task["status"] = "done"
            current_task["last_result"] = execution_result
            current_task["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            save_state(state)

            print(f"[META] Task {current_task['id']} marked done.")

        else:
            current_task["retries"] = current_task.get("retries", 0) + 1
            save_state(state)

    else:
        print("\n[EXECUTOR] No python code detected.")

    print("\n--- CYCLE COMPLETE ---\n")

    time.sleep(20)
