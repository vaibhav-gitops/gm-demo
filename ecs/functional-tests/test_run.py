import subprocess
import time
import json

# Configuration
PARENT_DIR = "."
TERRAFORM_DIR = "ecs/core-infra/terraform"
ROLLING_DIR = "ecs/rolling-update"
BG_DIR = "ecs/blue-green-update"
GIT_REPO = "https://github.com/vaibhav-gitops/gm-demo"
GIT_BRANCH = "test_setup"
CHECK_STATUS_API = "http://localhost:8080/api/v1/deployment/ecs"
MAX_WAIT_TIME = 300

# Deployment counters
success_count = 0
fail_count = 0


def run_command(command, cwd=None):
    """Run a shell command and return the output."""
    result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error running command: {command}\n{result.stderr}")
        return None
    return result.stdout.strip()


def setup_infra():
    """Run Terraform apply to create infrastructure."""
    print("🛠️ Setting up infrastructure using Terraform...")
    return run_command(f"terraform init && terraform apply -auto-approve"
                       f" && terraform output --json > terraform_output.json", cwd=TERRAFORM_DIR)


def create_push_commit(deployment_type):
    """Create and push a commit to trigger a deployment."""
    print("📌 Creating a new commit to trigger deployment...")
    run_command(f"git add . && git commit -m 'Test {deployment_type}' && git push", cwd=PARENT_DIR)
    commit_hash = run_command("git rev-parse HEAD", cwd=PARENT_DIR)
    return commit_hash


def trigger_rolling():
    print("📌 Triggering rolling deployment...")
    run_command(f"cp nginx_taskdef.json.sample nginx_taskdef.json && "
                f"cp nginx_svcdef.json.sample nginx_svcdef.json && "
                f"cp nginx_depdef.json.sample nginx_depdef.json && "
                f"cp nginx_input.json.sample nginx_input.json", cwd=ROLLING_DIR)
    commit_hash = create_push_commit("rolling")
    run_command(f"gmctl commit deploy -r {GIT_REPO} -b {GIT_BRANCH}", cwd=PARENT_DIR)
    return "rolling", commit_hash


def trigger_deployment():
    """Create and push a commit to trigger a deployment."""
    return trigger_rolling()


def check_deployment_status(deployment_type, commit_hash):
    """Poll the deployment status until it completes."""
    print(f"🔍 Checking {deployment_type} deployment status...")
    start_time = time.time()
    while time.time() - start_time < MAX_WAIT_TIME:
        status_response = run_command(f"curl -s '{CHECK_STATUS_API}?commit_hash={commit_hash}'")
        if status_response:
            status_data = json.loads(status_response)
            status = status_data.get("status")
            if status == "PROCESSED_SUCCESS":
                print(f"✅ {deployment_type} deployment succeeded!")
                return status
            elif status == "PROCESSED_ERROR":
                print(f"❌ {deployment_type} deployment failed.")
                return status
            else:
                print(f"⏳ {deployment_type} deployment is in progress... Waiting...")
        time.sleep(15)
    print(f"⚠️  {deployment_type} deployment timed out!")
    return "timeout"


def cleanup():
    """Delete resources and run Terraform destroy."""
    print("🧹 Cleaning up resources and destroying infrastructure...")
    run_command("terraform destroy -auto-approve", cwd=TERRAFORM_DIR)


def main():
    global success_count, fail_count
    if not setup_infra():
        print("❌ Failed to set up infrastructure. Exiting.")
        return

    for i in range(1):
        print(f"\n🚀 Starting test deployment {i + 1}...")
        deployment_type, commit_hash = trigger_deployment()
        status = check_deployment_status(deployment_type, commit_hash)

        if status == "PROCESSED_SUCCESS":
            success_count += 1
        else:
            fail_count += 1

    cleanup()
    print(f"\n📊 Deployment Results: ✅ {success_count} succeeded | ❌ {fail_count} failed.")


if __name__ == "__main__":
    main()