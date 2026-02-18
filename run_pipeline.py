import yaml
import requests
import subprocess
import time
import re
import os

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
# CODE EXTRACTION
# ============================================================

def extract_code(text):
    match = re.search(r"```python(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # fallback simple detection
    if "print(" in text or "open(" in text:
        return text.strip()

    return None


# ============================================================
# EXECUTOR
# ============================================================

def run_python(code):
    filename = f"generated_{int(time.time())}.py"

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
# MAIN LOOP
# ============================================================

print("\n--- META AGENT SERVICE STARTED ---\n")

while True:

    print("\n--- META AGENT CYCLE ---\n")

    # --------------------------------------------------------
    # LOAD YAML CONFIGS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # TASK QUEUE LOGIC
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # SUPERVISOR STEP
    # --------------------------------------------------------

    print("\nRunning supervisor...\n")

    supervisor_output = run_model(
        supervisor_model,
        user_goal,
        supervisor_system,
    )

    print("\nSupervisor says:\n")
    print(supervisor_output)

    # --------------------------------------------------------
    # CODER STEP
    # --------------------------------------------------------

    print("\nRunning coder agent...\n")

    coder_output = run_model(
        coder_model,
        supervisor_output,
        coder_system,
    )

    print("\nCoder output:\n")
    print(coder_output)

    # --------------------------------------------------------
    # EXECUTOR STEP
    # --------------------------------------------------------

    code = extract_code(coder_output)

    if code:
        execution_result = run_python(code)

        print("\nExecution result:\n")
        print(execution_result)

        # ----------------------------------------------------
        # FEEDBACK LOOP
        # ----------------------------------------------------

        print("\n[FEEDBACK LOOP] Sending result back to supervisor...\n")

        feedback_prompt = f"""
You are the supervisor reviewing execution results.

Original Goal:
{user_goal}

Coder Output:
{coder_output}

Execution Result:
{execution_result}

Decide:

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

        # ----------------------------------------------------
        # MARK TASK COMPLETE
        # ----------------------------------------------------

        if review.strip().startswith("COMPLETE"):
            current_task["status"] = "done"

            with open("project_state.yaml", "w") as f:
                yaml.dump(state, f)

            print(f"[META] Task {current_task['id']} marked done.")

    else:
        print("\n[EXECUTOR] No python code detected.")

    print("\n--- CYCLE COMPLETE ---\n")

    time.sleep(20)
