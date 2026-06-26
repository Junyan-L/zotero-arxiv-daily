import os
import shutil
import subprocess
from datetime import datetime
from loguru import logger
from omegaconf import DictConfig

def deploy_to_cloudflare(config: DictConfig):
    deploy_config = config.get("deploy")
    if not deploy_config or not deploy_config.get("enabled", False):
        logger.info("Cloudflare Pages deployment is disabled.")
        return

    cf_web_dir = deploy_config.get("cf_web_dir", "cf_web")
    project_name = deploy_config.get("project_name", "paper")
    
    source_html = "output.html"
    if not os.path.exists(source_html):
        logger.error(f"Source file {source_html} does not exist. Cannot deploy.")
        return

    # Ensure deployment directory exists
    os.makedirs(cf_web_dir, exist_ok=True)
    
    # 1. Copy to index.html (latest version)
    shutil.copy(source_html, os.path.join(cf_web_dir, "index.html"))
    
    # 2. Copy to {date}.html for historical archiving
    date_str = datetime.now().strftime("%Y-%m-%d")
    archive_html = os.path.join(cf_web_dir, f"{date_str}.html")
    shutil.copy(source_html, archive_html)
    logger.info(f"Copied {source_html} to {cf_web_dir}/index.html and {archive_html}")

    # 3. Deploy to Cloudflare Pages
    logger.info(f"Deploying directory '{cf_web_dir}' to Cloudflare Pages project '{project_name}'...")
    try:
        # Run wrangler pages deploy command
        result = subprocess.run(
            ["wrangler", "pages", "deploy", cf_web_dir, f"--project-name={project_name}", "--commit-dirty=true"],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info("Cloudflare Pages deployment succeeded!")
        logger.debug(f"Deployment output:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Cloudflare Pages deployment failed with exit code {e.returncode}")
        logger.error(f"Error output:\n{e.stderr}")
        logger.error(f"Standard output:\n{e.stdout}")
