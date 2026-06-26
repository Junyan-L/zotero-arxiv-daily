import requests
import feedparser
import re
from typing import Any
from time import sleep
from loguru import logger
from .base import BaseRetriever, register_retriever
from ..protocol import Paper


def clean_html(raw_html: str) -> str:
    """去除文本中的 HTML 标签并清理空白字符。"""
    if not raw_html:
        return ""
    # 去除常见标签
    cleanr = re.compile("<.*?>")
    cleantext = re.sub(cleanr, "", raw_html)
    # 替换多个连续空白为单个空格
    cleantext = re.sub(r"\s+", " ", cleantext)
    return cleantext.strip()


def extract_doi(raw_paper: dict) -> str | None:
    # 1. 尝试特定的键
    for key in ["prism_doi", "dc_identifier", "doi"]:
        if key in raw_paper:
            val = str(raw_paper[key])
            if val.lower().startswith("doi:"):
                return val[4:].strip()
            return val.strip()
    
    # 2. 从 link 中匹配 DOI (10.xxxx/xxxxx)
    link = raw_paper.get("link", "")
    match = re.search(r'(10\.\d{4,9}/[^\s&?#]+)', link, re.IGNORECASE)
    if match:
        doi = match.group(1)
        if doi.endswith("/"):
            doi = doi[:-1]
        return doi
    return None


def get_author_and_affiliation_from_doi(doi: str) -> tuple[list[str], list[str]]:
    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "User-Agent": "ZoteroArxivDaily/1.0 (mailto:your-email@example.com)"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        authors = data.get("message", {}).get("author", [])
        author_names = []
        affiliations = []
        for author in authors:
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip() if given and family else (given or family)
            if name:
                author_names.append(name)
            
            # 提取作者机构
            affs = author.get("affiliation", [])
            for aff in affs:
                name_aff = aff.get("name", "").strip()
                if name_aff:
                    affiliations.append(name_aff)
        
        # 精炼和去重机构
        cleaned_affs = []
        for aff in affiliations:
            if aff not in cleaned_affs:
                cleaned_affs.append(aff)
                
        return author_names, cleaned_affs
    except Exception as e:
        logger.warning(f"Failed to fetch authors/affiliations from CrossRef for DOI {doi}: {e}")
        return [], []


@register_retriever("rss")
class RssRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        self.urls = self.retriever_config.get("urls") or []
        if not self.urls:
            logger.warning("No RSS URLs configured for RssRetriever.")

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        all_entries = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 兼容单独配置为一个字符串的情况
        if isinstance(self.urls, str):
            self.urls = [self.urls]

        for url in self.urls:
            logger.info(f"Fetching RSS feed from: {url}")
            retry_num = 3
            delay_time = 5
            response_content = None
            
            for i in range(retry_num):
                try:
                    response = requests.get(url, headers=headers, timeout=(10, 30))
                    response.raise_for_status()
                    response_content = response.content
                    break
                except Exception as e:
                    if i == retry_num - 1:
                        logger.error(f"Failed to fetch RSS from {url}: {e}")
                    else:
                        logger.warning(f"Failed to fetch RSS from {url}: {e}. Retrying in {delay_time} seconds...")
                        sleep(delay_time)
            
            if response_content:
                try:
                    feed = feedparser.parse(response_content)
                    if feed.bozo:
                        logger.warning(f"RSS parse warning (bozo) for {url}: {feed.bozo_exception}")
                    
                    entries = feed.entries
                    logger.info(f"Found {len(entries)} entries in {url}")
                    all_entries.extend(entries)
                except Exception as e:
                    logger.error(f"Failed to parse RSS xml from {url}: {e}")
        
        if self.config.executor.debug:
            all_entries = all_entries[:10]
        return all_entries

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        title = clean_html(raw_paper.get("title", ""))
        if not title:
            logger.warning("Skipping RSS entry with empty title.")
            return None

        # 过滤掉非论文的期刊卷期信息、目录及封面等杂音数据
        noise_keywords = ["issue information", "table of contents", "editorial board", "front cover", "back cover"]
        title_lower = title.lower()
        if any(kw in title_lower for kw in noise_keywords):
            logger.info(f"Filtering out journal metadata noise: '{title}'")
            return None

        # 尝试提取 DOI
        doi = extract_doi(raw_paper)

        # 尝试不同方式获取作者
        authors = []
        if "authors" in raw_paper:
            authors = [a.get("name", "").strip() for a in raw_paper["authors"] if a.get("name")]
        elif "author" in raw_paper:
            authors = [raw_paper["author"].strip()]
        elif "author_detail" in raw_paper:
            authors = [raw_paper["author_detail"].get("name", "").strip()]
        
        authors = [a for a in authors if a]
        if not authors:
            authors = ["Unknown"]

        # 获取摘要并清洗 HTML
        abstract = raw_paper.get("summary", "")
        if not abstract:
            abstract = raw_paper.get("description", "")
        abstract = clean_html(abstract)

        # 获取链接
        url = raw_paper.get("link", "")

        # 尝试获取 PDF 链接
        pdf_url = None
        if "links" in raw_paper:
            for link_item in raw_paper["links"]:
                if (
                    link_item.get("type") == "application/pdf"
                    or link_item.get("href", "").endswith(".pdf")
                ):
                    pdf_url = link_item.get("href")
                    break
        if not pdf_url and url.endswith(".pdf"):
            pdf_url = url

        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            full_text=None,
            doi=doi,
        )
