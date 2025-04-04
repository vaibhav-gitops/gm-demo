import subprocess
import time
import json

# Configuration
PARENT_DIR = "."
TERRAFORM_DIR = "ecs/core-infra/terraform"
ROLLING_DIR = "ecs/rolling-update"
BG_DIR = "ecs/blue-green-update"
GIT_REPO = "https://github.com/vaibhav-gitops/gm-demo"
GIT_BRANCH = ""
ACCESS_TOKEN = "GITHUB_TOKEN"
CHECK_STATUS_API = "http://localhost:8080/api/v1/deployments/ecs"
ADD_REPO_API = "http://localhost:8080/api/v1/repositories/add"
MAX_WAIT_TIME = 300


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


def add_gitmoxi_repo():
    """Run Terraform apply to create infrastructure."""
    print("🛠️ Adding Repo and Branch in Gitmoxi...")
    payload = json.dumps({
        "repo_url": GIT_REPO,
        "branches": [GIT_BRANCH],
        "access_token_arn": ACCESS_TOKEN
    })

    headers = "-H 'Content-Type: application/json'"
    command = f"curl -s -X POST {ADD_REPO_API} {headers} -d '{payload}'"

    response = run_command(command)

    if response:
        response_data = json.loads(response)
        status = response_data.get("success")
        if status == "true":
            print(f"✅ Repository {GIT_REPO} added successfully!")
            return status
        else:
            print(f"❌ Failed to add repository {GIT_REPO}. Status: {status}")
            return status
    else:
        print(f"⚠️ No response from server while adding repository {GIT_REPO}.")
        return "error"


def create_push_commit(deployment_type):
    """Create and push a commit to trigger a deployment."""
    print("📌 Creating a new commit to trigger deployment...")
    run_command(f"git add . && git commit -m 'Test {deployment_type}' && "
                f"git push --set-upstream origin {GIT_BRANCH}", cwd=PARENT_DIR)
    commit_hash = run_command("git rev-parse HEAD", cwd=PARENT_DIR)
    return commit_hash


def trigger_rolling():
    print("\n📌 Triggering rolling deployment...")
    run_command(f"cp nginx_taskdef.json.sample nginx_taskdef.json && "
                f"cp nginx_svcdef.json.sample nginx_svcdef.json && "
                f"cp nginx_depdef.json.sample nginx_depdef.json && "
                f"cp nginx_input.json.sample nginx_input.json", cwd=ROLLING_DIR)
    commit_hash = create_push_commit("rolling")
    run_command(f"gmctl commit deploy -r {GIT_REPO} -b {GIT_BRANCH}", cwd=PARENT_DIR)
    return "rolling", commit_hash


def trigger_rolling_update():
    print("\n📌 Triggering rolling update deployment...")
    run_command("sed -i '' 's|\"public.ecr.aws/nginx/nginx:latest\"|\"public.ecr.aws/docker/library/httpd:alpine3.20\"|' nginx_input.json",
                cwd=ROLLING_DIR)
    commit_hash = create_push_commit("rolling update")
    run_command(f"gmctl commit deploy -r {GIT_REPO} -b {GIT_BRANCH}", cwd=PARENT_DIR)
    return "rolling update", commit_hash


def trigger_blue_green():
    print("\n📌 Triggering blue-green deployment...")
    run_command(f"cp bg_nginx_taskdef.json.sample bg_nginx_taskdef.json && "
                f"cp bg_nginx_svcdef.json.sample bg_nginx_svcdef.json && "
                f"cp bg_nginx_depdef.json.sample bg_nginx_depdef.json && "
                f"cp bg_nginx_input.json.sample bg_nginx_input.json", cwd=BG_DIR)
    commit_hash = create_push_commit("blue-green")
    run_command(f"gmctl commit deploy -r {GIT_REPO} -b {GIT_BRANCH}", cwd=PARENT_DIR)
    return "blue-green", commit_hash


def trigger_blue_green_update():
    print("\n📌 Triggering blue-green update deployment...")
    run_command("sed -i '' 's|\"public.ecr.aws/nginx/nginx:latest\"|\"public.ecr.aws/docker/library/httpd:alpine3.20\"|' bg_nginx_input.json",
                cwd=BG_DIR)
    commit_hash = create_push_commit("blue-green update")
    run_command(f"gmctl commit deploy -r {GIT_REPO} -b {GIT_BRANCH}", cwd=PARENT_DIR)
    return "blue-green update", commit_hash


def trigger_monitor_deployments():
    """Trigger and monitor all deployment types in order."""
    deployment_functions = [
        trigger_rolling,
        trigger_rolling_update,
        trigger_blue_green,
        trigger_blue_green_update
    ]

    success_count = 0
    fail_count = 0

    for trigger_function in deployment_functions:
        deployment_type, commit_hash = trigger_function()
        time.sleep(15)  # Wait before checking status
        status = check_deployment_status(deployment_type, commit_hash)

        if status == "PROCESSED_SUCCESS":
            print(f"✅ {deployment_type} deployment succeeded!")
            success_count += 1
        else:
            print(f"❌ {deployment_type} deployment failed.")
            fail_count += 1

    # Print final report
    print("\n📊 Deployment Summary:")
    print(f"✅ Successful Deployments: {success_count}")
    print(f"❌ Failed Deployments: {fail_count}")


def check_deployment_status(deployment_type, commit_hash):
    """Poll the deployment status until it completes."""
    print(f"🔍 Checking {deployment_type} deployment status...")
    start_time = time.time()

    while time.time() - start_time < MAX_WAIT_TIME:
        url = f"{CHECK_STATUS_API}?commit_hash={commit_hash}&n=1"
        status_response = run_command(f"curl -s -X GET '{url}'")

        if status_response:
            status_data = json.loads(status_response)
            status = status_data.get('deployments')[0].get("status")
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
    run_command("aws ecs delete-service --cluster gitmoxidemo --service rolling-nginx-svc --region us-west-2 --force",
                cwd=PARENT_DIR)
    run_command("aws ecs delete-service --cluster gitmoxidemo --service bg-nginx-svc --region us-west-2 --force",
                cwd=PARENT_DIR)
    run_command("terraform destroy -auto-approve", cwd=TERRAFORM_DIR)


def main():
    global GIT_BRANCH
    if not setup_infra():
        print("❌ Failed to set up infrastructure. Exiting.")
        return

    GIT_BRANCH = run_command("git rev-parse --abbrev-ref HEAD", cwd=PARENT_DIR)
    add_gitmoxi_repo()
    trigger_monitor_deployments()
    cleanup()


if __name__ == "__main__":
    main()