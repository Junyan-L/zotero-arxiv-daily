import pytest
from omegaconf import open_dict
from types import SimpleNamespace
import requests
from zotero_arxiv_daily.retriever.rss_retriever import RssRetriever, clean_html


def test_clean_html():
    html_text = "<p>Hello <b>World</b>!</p>\n  Spacing  "
    assert clean_html(html_text) == "Hello World! Spacing"
    assert clean_html(None) == ""


def test_rss_retrieve(config, monkeypatch):
    # Mock sleep
    monkeypatch.setattr("zotero_arxiv_daily.retriever.base.sleep", lambda _: None)

    xml_content = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
    <channel>
     <title>Example RSS Feed</title>
     <link>https://example.com</link>
     <description>Example RSS Feed Description</description>
     <item>
      <title>An RSS Paper Title</title>
      <link>https://example.com/paper1.pdf</link>
      <description>&lt;p&gt;This is an &lt;b&gt;awesome&lt;/b&gt; paper abstract.&lt;/p&gt;</description>
      <author>Author A, Author B</author>
      <guid>https://example.com/paper1</guid>
     </item>
    </channel>
    </rss>
    """

    def mock_get(url, **kwargs):
        return SimpleNamespace(
            status_code=200,
            content=xml_content.encode("utf-8"),
            raise_for_status=lambda: None
        )

    monkeypatch.setattr(requests, "get", mock_get)

    with open_dict(config.source):
        config.source.rss = {"urls": ["https://example.com/rss.xml"]}
    
    retriever = RssRetriever(config)
    papers = retriever.retrieve_papers()
    
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "An RSS Paper Title"
    assert paper.authors == ["Author A, Author B"]
    assert paper.abstract == "This is an awesome paper abstract."
    assert paper.url == "https://example.com/paper1.pdf"
    assert paper.pdf_url == "https://example.com/paper1.pdf"
    assert paper.source == "rss"
    assert paper.full_text is None


def test_rss_convert_to_paper(config):
    with open_dict(config.source):
        config.source.rss = {"urls": ["https://example.com/rss.xml"]}
    
    retriever = RssRetriever(config)
    
    raw_paper = {
        "title": "Another Paper",
        "author": "Dr. Smith",
        "summary": "Summary text",
        "link": "https://example.com/paper2",
        "links": [
            {"href": "https://example.com/paper2.pdf", "type": "application/pdf"},
            {"href": "https://example.com/paper2", "type": "text/html"}
        ]
    }
    
    paper = retriever.convert_to_paper(raw_paper)
    assert paper.title == "Another Paper"
    assert paper.authors == ["Dr. Smith"]
    assert paper.abstract == "Summary text"
    assert paper.url == "https://example.com/paper2"
    assert paper.pdf_url == "https://example.com/paper2.pdf"
    assert paper.source == "rss"


def test_rss_empty_urls(config):
    with open_dict(config.source):
        config.source.rss = {"urls": None}
    
    retriever = RssRetriever(config)
    assert retriever.urls == []


def test_rss_convert_to_paper_with_dc_description(config):
    with open_dict(config.source):
        config.source.rss = {"urls": ["https://example.com/rss.xml"]}
    
    retriever = RssRetriever(config)
    
    # Verify dc_description is prioritized even if summary and description are present
    raw_paper = {
        "title": "A Paper with DC Description",
        "author": "Dr. Jones",
        "summary": "Volume 1, Issue 2 (Summary)",
        "description": "Volume 1, Issue 2 (Description)",
        "dc_description": "This is the actual paper abstract from Dublin Core.",
        "link": "https://example.com/paper3"
    }
    
    paper = retriever.convert_to_paper(raw_paper)
    assert paper.abstract == "This is the actual paper abstract from Dublin Core."
