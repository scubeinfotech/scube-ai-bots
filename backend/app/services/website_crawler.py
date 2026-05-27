from sqlalchemy.sql import func
import re
from typing import Set
from urllib.parse import urlparse, urljoin
import requests
"""
Website crawler service for tenant onboarding.
Fetches same-domain pages, extracts clean text, stores documents,
and updates tenant knowledge_context for immediate chat improvement.
"""

from collections import deque
import hashlib
import json
import asyncio
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.database import SessionLocal
from app.models import Tenant, Document
from app.services.vector_knowledge import VectorKnowledgeService


class PlaywrightRenderer:
    """Use Playwright for JavaScript-rendered websites."""
    
    @staticmethod
    async def fetch_page(url: str, timeout: int = 30) -> Optional[str]:
        """Fetch fully rendered HTML using Playwright headless browser."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                content = await page.content()
                await browser.close()
                return content
        except Exception as e:
            print(f"Playwright error for {url}: {e}")
            return None

class WebsiteCrawlerService:
    MAX_PAGES = 25  # Default maximum number of pages to crawl per tenant website
    USER_AGENT = "Mozilla/5.0 (compatible; CentralizedLLMCrawler/1.0; +https://yourdomain.com/bot)"
    REQUEST_TIMEOUT = 10  # seconds
    MAX_TEXT_CHARS = 8000
    FACT_TOPIC_KEYWORDS = {
        "offerings": ["service", "solution", "product", "platform", "offer", "provide", "deliver"],
        "expertise": ["expertise", "specialize", "skill", "experience", "knowledge", "proficient"],
        "industry": ["industry", "sector", "market", "segment", "domain"],
        "methodology": ["approach", "process", "methodology", "framework", "step", "phase"],
    }

    @staticmethod
    def _extract_structured_contact(soup) -> Dict[str, str]:
        contact: Dict[str, str] = {}
        # Extract JSON-LD (schema.org)
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            objects = payload if isinstance(payload, list) else [payload]
            for item in objects:
                if not isinstance(item, dict):
                    continue
                for candidate in WebsiteCrawlerService._iter_structured_items(item):
                    if not isinstance(candidate, dict):
                        continue
                    # Business info
                    name = candidate.get("name")
                    if name and not contact.get("name"):
                        contact["name"] = str(name)
                    # Contact info
                    email = candidate.get("email")
                    telephone = candidate.get("telephone")
                    address = candidate.get("address")
                    if email and not contact.get("email"):
                        contact["email"] = str(email)
                    if telephone and not contact.get("phone"):
                        contact["phone"] = str(telephone)
                    if isinstance(address, dict) and not contact.get("address"):
                        pieces = [
                            str(address.get("streetAddress") or "").strip(),
                            str(address.get("addressLocality") or "").strip(),
                            str(address.get("postalCode") or "").strip(),
                        ]
                        pretty = ", ".join([p for p in pieces if p])
                        if pretty:
                            contact["address"] = pretty
                    elif isinstance(address, str) and address.strip() and not contact.get("address"):
                        contact["address"] = address.strip()
        # Extract microdata (itemprop)
        for tag in soup.find_all(attrs={"itemprop": True}):
            itemprop = tag.get("itemprop")
            value = tag.get("content") or tag.get_text(strip=True)
            if not value:
                continue
            if itemprop in ["name", "email", "telephone", "address"] and not contact.get(itemprop):
                contact[itemprop] = value
        return contact


    @classmethod
    def queue_crawl(cls, background_tasks, tenant_id: str, website_url: str, include_footer: bool = False) -> None:
        """Queue crawl job through FastAPI background tasks."""
        background_tasks.add_task(cls.crawl_and_ingest, tenant_id, website_url, include_footer)


    @classmethod
    def crawl_and_ingest(cls, tenant_id: str, website_url: str, include_footer: bool = False) -> None:
        """Crawl website, store documents, and merge extracted content into tenant knowledge."""
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant or not website_url:
                return

            tenant.onboarding_stage = "processing"
            cls._update_crawl_progress(db, tenant, 5, "Starting website crawl...")
            db.commit()

            source_url = None
            pages: List[Dict[str, Any]] = []
            cls._update_crawl_progress(db, tenant, 10, "Discovering website pages...")
            for candidate_url in cls._candidate_urls(tenant, website_url):
                pages = cls._crawl_site(candidate_url, max_pages=cls.MAX_PAGES, include_footer=include_footer)
                if pages:
                    source_url = candidate_url
                    break

            unique_pages = cls._dedupe_pages(pages)
            cls._update_crawl_progress(db, tenant, 30, f"Processing {len(unique_pages)} discovered pages...")

            cls._deactivate_existing_crawl_documents(db, tenant_id)
            cls._update_crawl_progress(db, tenant, 40, "Clearing old crawl data...")

# Clear previous crawl data from knowledge context before merging new data
            context = tenant.knowledge_context
            if context:
                # CRITICAL: Clear old data whether it's dict OR string
                if isinstance(context, dict):
                    # Remove all old crawl related data
                    for key in ["company_overview", "contact_info", "official_contact", 
                             "business_facts", "website_pages", "website_crawl"]:
                        if key in context:
                            del context[key]
                    tenant.knowledge_context = context
                elif isinstance(context, str) and len(context) > 0:
                    # If string format with old crawl data - log warning and clear it
                    if any(word in context.lower() for word in ["ship design", "consultation", "marine engineering services"]):
                        print(f"[WARNING] Old crawl data detected for {tenant.slug}: Clearing {len(context)} chars of legacy text")
                    tenant.knowledge_context = None  # Clear entirely - will be replaced with fresh data
            
            # Also reset any hardcoded prompt template that was overriding crawl data
            if hasattr(tenant, 'prompt_template') and tenant.prompt_template:
                tenant.prompt_template = None

            total_pages = len(unique_pages)
            for idx, page in enumerate(unique_pages):
                document = Document(
                    tenant_id=tenant_id,
                    name=page["title"][:255] or "Website Page",
                    file_path=page["url"],
                    content=cls._build_document_content(page),
                    document_type="website_page",
                    category="website-crawl",
                    is_processed=True,
                    is_active=True,
                )
                db.add(document)
                db.flush()
                VectorKnowledgeService.index_document(db, document)
                
                progress = 45 + int(((idx + 1) / total_pages) * 40)
                cls._update_crawl_progress(db, tenant, progress, f"Indexed page {idx + 1} of {total_pages}...")

            cls._update_crawl_progress(db, tenant, 90, "Finalizing knowledge context...")

            merged_context = cls._merge_knowledge_context(
                tenant.knowledge_context,
                tenant,
                unique_pages,
                source_url or website_url,
            )
            tenant.knowledge_context = merged_context
            flag_modified(tenant, "knowledge_context")
            tenant.onboarding_stage = "ready"
            tenant.onboarding_notes = cls._build_completion_note(
                tenant.onboarding_notes or "",
                len(unique_pages),
                source_url or website_url,
            )
            cls._update_crawl_progress(db, tenant, 100, "Crawl completed successfully!")
            db.commit()
        except Exception as exc:
            db.rollback()
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                tenant.onboarding_stage = "discovering"
                tenant.onboarding_notes = f"Website crawl failed: {str(exc)[:400]}"
                cls._update_crawl_progress(db, tenant, 0, f"Crawl failed: {str(exc)[:100]}")
                db.commit()
        finally:
            db.close()

    @classmethod
    def get_crawl_status(cls, db: Session, tenant_id: str) -> Dict[str, Any]:
        """Return current crawl status and count of crawled documents."""
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {}

        document_count = db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.document_type == "website_page",
            Document.is_active == True,
        ).count()

        # Get knowledge context for debugging
        knowledge = tenant.knowledge_context if isinstance(tenant.knowledge_context, dict) else {}
        contact_info = knowledge.get("contact_info", "")
        
        return {
            "tenant_id": tenant.id,
            "website_url": tenant.website_url,
            "onboarding_stage": tenant.onboarding_stage,
            "document_count": document_count,
            "onboarding_notes": tenant.onboarding_notes,
            "contact_info_stored": contact_info if contact_info else "NOT FOUND",
            "crawl_progress_percent": tenant.crawl_progress_percent,
            "crawl_progress_stage": tenant.crawl_progress_stage,
            "crawl_progress_updated_at": tenant.crawl_progress_updated_at.isoformat() if tenant.crawl_progress_updated_at else None,
        }

    @classmethod
    def _fetch_sitemap_urls(cls, base_url: str) -> List[str]:
        """Fetch URLs from XML sitemap if available."""
        parsed = urlparse(base_url)
        sitemap_urls = [
            f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
            f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
            f"{parsed.scheme}://{parsed.netloc}/sitemap-index.xml",
        ]
        headers = {"User-Agent": cls.USER_AGENT}
        
        for sitemap_url in sitemap_urls:
            try:
                response = requests.get(sitemap_url, headers=headers, timeout=cls.REQUEST_TIMEOUT)
                if response.status_code == 200 and "xml" in response.headers.get("content-type", ""):
                    urls = cls._parse_sitemap_xml(response.text)
                    if urls:
                        print(f"[Crawler] Found {len(urls)} URLs from sitemap: {sitemap_url}")
                        return urls
            except Exception as e:
                continue
        return []

    @classmethod
    def _parse_sitemap_xml(cls, xml_content: str) -> List[str]:
        """Parse XML sitemap and extract URLs."""
        try:
            from xml.etree import ElementTree as ET
            root = ET.fromstring(xml_content)
            namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls = []
            
            for url_elem in root.findall(".//sm:url", namespaces) or root.findall(".//url"):
                loc = url_elem.find("sm:loc", namespaces) or url_elem.find("loc")
                if loc is not None and loc.text:
                    urls.append(loc.text)
            
            if not urls:
                for elem in root.findall(".//sm:loc", namespaces) or root.findall(".//loc"):
                    if elem.text:
                        urls.append(elem.text)
            
            return urls
        except Exception as e:
            print(f"[Crawler] Sitemap XML parse error: {e}")
            return []

    @classmethod
    def _crawl_site(cls, start_url: str, max_pages: int = 6, include_footer: bool = False) -> List[Dict[str, Any]]:
        """BFS crawl of same-host pages, capped at ``max_pages``.

        Each URL is fetched with ``requests`` first; if the response looks
        JS-rendered (empty / loading-shell HTML) or the request fails entirely,
        we fall back to Playwright for that URL. Discovered links from each
        rendered page are pushed onto the queue so the crawl can continue
        beyond the start URL.

        Note: the BFS loop here was missing in a previous refactor that added
        Playwright support, which caused every crawl to return exactly one
        page (the start URL) regardless of ``max_pages``. See website_crawler.py.bak
        for the original loop. Restoring it is the fix for the
        "re-crawl only picks up 1 page" regression.
        """
        headers = {"User-Agent": cls.USER_AGENT}
        base_host = urlparse(start_url).netloc
        queue = deque([start_url])
        seen: Set[str] = set()
        pages: List[Dict[str, Any]] = []

        sitemap_urls = cls._fetch_sitemap_urls(start_url)
        for url in sitemap_urls:
            parsed = urlparse(url)
            if parsed.netloc == base_host:
                norm = cls._normalize_url(url)
                if norm and norm not in seen:
                    queue.append(norm)

        while queue and len(pages) < max_pages:
            url = queue.popleft()
            normalized = cls._normalize_url(url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)

            html = ""
            try:
                response = requests.get(normalized, headers=headers, timeout=cls.REQUEST_TIMEOUT)
                content_type = response.headers.get("content-type", "")
                if response.status_code == 200 and "text/html" in content_type:
                    html = response.text
                    # Heuristic: if the HTML looks like a JS loading-shell,
                    # re-fetch the same URL through Playwright so we get the
                    # post-render DOM instead of an empty skeleton.
                    if (
                        len(html) < 2000
                        or "Please wait" in html
                        or "Starting the" in html
                    ):
                        try:
                            rendered = asyncio.run(PlaywrightRenderer.fetch_page(normalized))
                            if rendered:
                                html = rendered
                        except Exception as render_err:
                            print(f"[Crawler] Playwright render failed for {normalized}: {render_err}")
            except Exception as e:
                print(f"[Crawler] requests.get failed for {normalized}: {e}; trying Playwright")
                try:
                    rendered = asyncio.run(PlaywrightRenderer.fetch_page(normalized))
                    if rendered:
                        html = rendered
                except Exception as render_err:
                    print(f"[Crawler] Playwright also failed for {normalized}: {render_err}")
                    continue

            if not html:
                continue

            page = cls._extract_page(normalized, html, include_footer=include_footer)
            if not page:
                continue

            pages.append(page)
            for link in page.get("links", []):
                parsed = urlparse(link)
                if parsed.netloc != base_host:
                    continue
                norm_link = cls._normalize_url(link)
                if norm_link and norm_link not in seen:
                    queue.append(norm_link)

        return pages


    @classmethod
    def _extract_page(cls, url: str, html: str, include_footer: bool = False) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        structured_contact = cls._extract_structured_contact(soup)
        special_links = cls._extract_special_contact_links(soup, url)

        # Extract footer content before removing tags
        footer_content = ""
        if include_footer:
            footer = soup.find("footer")
            if footer:
                footer_content = cls._clean_text(footer.get_text(" ", strip=True))
            
            # Also look for divs with footer class (common pattern)
            if not footer_content:
                footer_divs = soup.find_all("div", class_=lambda x: x and "footer" in str(x).lower())
                for div in footer_divs:
                    div_text = cls._clean_text(div.get_text(" ", strip=True))
                    if div_text and len(div_text) > 20:
                        footer_content = div_text
                        break
            
            # Also look for contact info in header, contact sections, or common contact patterns
            contact_sections = soup.find_all(["header", "div", "section"], class_=lambda x: x and any(c in str(x).lower() for c in ["contact", "footer", "address", "phone"]))
            for section in contact_sections:
                section_text = cls._clean_text(section.get_text(" ", strip=True))
                if section_text and len(section_text) > 10:
                    if footer_content:
                        footer_content += " " + section_text
                    else:
                        footer_content = section_text

        tags_to_remove = ["script", "style", "noscript", "svg"]
        if not include_footer:
            tags_to_remove.append("footer")
        for tag in soup(tags_to_remove):
            tag.decompose()

        title = cls._clean_text((soup.title.string.strip() if soup.title and soup.title.string else "") or url)
        meta_description = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_description = cls._clean_text(meta_tag["content"].strip())

        text_blocks = []


        seen_blocks: Set[str] = set()
        for selector in ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]:
            for node in soup.select(selector):
                text = cls._clean_text(" ".join(node.get_text(" ", strip=True).split()))
                if text and len(text) > 20 and text not in seen_blocks:
                    seen_blocks.add(text)
                    text_blocks.append(text)

        important_blocks = soup.find_all(
            ["div", "section", "article"],
            class_=lambda value: value and any(
                token in str(value).lower()
                for token in ["team", "member", "leadership", "contact-option", "contact-item", "position"]
            ),
        )
        for node in important_blocks:
            text = cls._clean_text(" ".join(node.get_text(" ", strip=True).split()))
            if text and len(text) > 30 and text not in seen_blocks:
                seen_blocks.add(text)
                text_blocks.append(text)

        full_text = "\n".join(text_blocks)
        if not full_text:
            return None

        headings = []
        for node in soup.select("h1, h2, h3"):
            text = cls._clean_text(" ".join(node.get_text(" ", strip=True).split()))
            if text:
                headings.append(text)

        links = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            absolute = cls._normalize_url(urljoin(url, href))
            if absolute:
                links.append(absolute)

        # Extract contact info from both footer AND main content
        contact_info = ""
        # First try footer if included
        if include_footer and footer_content:
            contact_info = cls._extract_contact_info(footer_content)
        # Also extract from main content to catch contact details on the page
        content_contact = cls._extract_contact_info(full_text)
        # Combine both, avoiding duplicates
        if content_contact:
            if contact_info:
                # Merge unique parts from both sources
                existing = set(contact_info.split(" | "))
                for part in content_contact.split(" | "):
                    if part not in existing:
                        contact_info += " | " + part
            else:
                contact_info = content_contact

        # Merge structured contact and special links into contact blob.
        extra_contact_parts = []
        for key in ["address", "phone", "email", "whatsapp"]:
            value = structured_contact.get(key)
            if value:
                extra_contact_parts.append(str(value).strip())
        for value in special_links.values():
            if value:
                extra_contact_parts.append(str(value).strip())
        if extra_contact_parts:
            existing = set([part.strip() for part in contact_info.split(" | ") if part.strip()]) if contact_info else set()
            merged_parts = [part for part in extra_contact_parts if part and part not in existing]
            if merged_parts:
                contact_info = " | ".join(([contact_info] if contact_info else []) + merged_parts)

        business_facts = cls._extract_business_facts(
            title=title,
            description=meta_description,
            headings=headings,
            content=full_text,
            url=url,
        )

        return {
            "url": url,
            "title": title[:255],
            "description": meta_description[:500],
            "headings": headings[:10],
            "summary": full_text[:800],
            "content": full_text[:cls.MAX_TEXT_CHARS],
            "links": links,
            "footer_content": footer_content[:2000] if footer_content else "",
            "contact_info": contact_info,
            "structured_contact": structured_contact,
            "special_links": special_links,
            "business_facts": business_facts,
        }

    @classmethod
    def _build_document_content(cls, page: Dict[str, Any]) -> str:
        headings = page.get("headings") or []
        sections = [
            f"Title: {page.get('title', '')}",
            f"URL: {page.get('url', '')}",
        ]
        if page.get("description"):
            sections.append(f"Description: {page['description']}")
        if headings:
            sections.append("Headings:\n- " + "\n- ".join(headings[:8]))
        # Add contact info if available
        contact_info = page.get("contact_info", "")
        if contact_info:
            sections.append(f"Contact Info: {contact_info}")
        special_links = page.get("special_links") or {}
        if special_links:
            link_parts = [f"{label.capitalize()}: {value}" for label, value in special_links.items() if value]
            if link_parts:
                sections.append("Contact Links: " + " | ".join(link_parts))
        business_facts = page.get("business_facts") or []
        if business_facts:
            sections.append(
                "Business Facts:\n- " + "\n- ".join([
                    f"{fact.get('topic', 'general').capitalize()}: {fact.get('statement', '')}" for fact in business_facts[:8]
                ])
            )
        sections.append("Content:\n" + (page.get("content") or ""))
        return "\n\n".join(sections).strip()

    @classmethod
    def _extract_products_from_pages(cls, pages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Extract product/software names from pages."""
        product_indicators = [
            "software", "platform", "app", "tool", "system", "solution", "product",
            "pro ", "360", "plus", "premium", "enterprise", "edition", "version"
        ]
        exclude_words = ["home", "about", "contact", "thank", "chinese", "new year", 
                        "testimonial", "client", "team", "gallery", "blog", "news", "faq",
                        "who should", "use case", "related to", "is chronobill"]
        
        product_names: Dict[str, str] = {}
        
        for page in pages:
            url = page.get("url", "").lower()
            content = page.get("content", "").lower()
            headings = page.get("headings", [])
            
            url_path = urlparse(url).path
            if url_path and any(ind in url_path.lower() for ind in product_indicators):
                part = url_path.replace(".html", "").replace("-", " ").strip()
                if len(part) > 3 and part.lower() not in product_names:
                    product_names[part.lower()] = part.title()
            
            for heading in headings:
                heading_lower = heading.lower()
                if any(ex in heading_lower for ex in exclude_words):
                    continue
                name = heading.strip()
                
                has_product_indicator = any(ind in heading_lower for ind in product_indicators)
                is_likely_product = (
                    len(name) > 5 and len(name) < 50 and
                    name[0].isupper() and
                    not name.lower().startswith(("what", "how", "why", "who", "when", "where")) and
                    not any(ex in heading_lower for ex in ["services", "our ", "we ", "best "])
                )
                
                if has_product_indicator or (is_likely_product and len(name.split()) <= 4):
                    if name.lower() not in product_names:
                        product_names[name.lower()] = name
            
            import re
            product_patterns = [
                r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z]?[a-zA-Z]+){1,3})\s+(?:software|platform|app|solution|tool|system)\b',
                r'\b(?:ServiceDesk|Chronobill|AI[\s-]?(?:Powered|Search)|Cloud[\s-]?Migration|Tender[\s-]?Automation)\b',
            ]
            for pattern in product_patterns:
                matches = re.findall(pattern, content)
                for m in matches:
                    if isinstance(m, str) and len(m) > 3:
                        if m.lower() not in product_names:
                            product_names[m.lower()] = m
        
        return [{"name": v} for v in list(product_names.values())[:15]]

    @classmethod
    def _merge_knowledge_context(
        cls,
        existing_context: Any,
        tenant: Tenant,
        pages: List[Dict[str, Any]],
        source_url: str,
    ) -> Dict[str, Any]:
        context = existing_context if isinstance(existing_context, dict) else {}
        website_pages = [
            {
                "title": page.get("title"),
                "url": page.get("url"),
                "summary": page.get("summary"),
                "description": page.get("description"),
                "headings": page.get("headings", []),
                "contact_info": page.get("contact_info", ""),
                "business_facts": page.get("business_facts", []),
            }
            for page in pages
        ]

        if pages:
            homepage = pages[0]
            context["company_overview"] = homepage.get("summary") or homepage.get("description") or context.get("company_overview")

        # Collect all contact info from pages
        all_contact_info = []
        for page in pages:
            contact = page.get("contact_info", "")
            if contact and contact not in all_contact_info:
                all_contact_info.append(contact)
        
        if all_contact_info:
            context["contact_info"] = " ".join(all_contact_info)

        # Use newly crawled contact info (always prefer new over old during re-crawl)
        official_contact: Dict[str, str] = {}
        for page in pages:
            structured = page.get("structured_contact") if isinstance(page.get("structured_contact"), dict) else {}
            special_links = page.get("special_links") if isinstance(page.get("special_links"), dict) else {}
            
            # Update each field if found in crawl
            for key in ["address", "phone", "email", "whatsapp"]:
                if structured.get(key):
                    official_contact[key] = structured.get(key)
            
            if special_links.get("whatsapp"):
                official_contact["whatsapp"] = special_links.get("whatsapp")

        # Always update contact info during crawl
        if official_contact:
            context["official_contact"] = official_contact

        existing_facts = context.get("business_facts") if isinstance(context.get("business_facts"), list) else []
        merged_facts: List[Dict[str, str]] = []
        seen_fact_keys: Set[str] = set()
        for fact in existing_facts:
            if not isinstance(fact, dict):
                continue
            topic = str(fact.get("topic") or "general").strip().lower()
            statement = cls._clean_text(str(fact.get("statement") or ""))
            if not statement:
                continue
            key = f"{topic}:{statement.lower()}"
            if key in seen_fact_keys:
                continue
            seen_fact_keys.add(key)
            merged_facts.append({
                "topic": topic,
                "statement": statement,
                "source_url": str(fact.get("source_url") or "").strip(),
                "title": str(fact.get("title") or "").strip(),
            })

        for page in pages:
            for fact in page.get("business_facts") or []:
                if not isinstance(fact, dict):
                    continue
                topic = str(fact.get("topic") or "general").strip().lower()
                statement = cls._clean_text(str(fact.get("statement") or ""))
                if not statement:
                    continue
                key = f"{topic}:{statement.lower()}"
                if key in seen_fact_keys:
                    continue
                seen_fact_keys.add(key)
                merged_facts.append({
                    "topic": topic,
                    "statement": statement,
                    "source_url": str(fact.get("source_url") or page.get("url") or "").strip(),
                    "title": str(fact.get("title") or page.get("title") or "").strip(),
                })

        if merged_facts:
            context["business_facts"] = merged_facts[:20]

        # Extract offerings facts into services list
        services_list = []
        products_list = []
        seen_items = set()
        
        for fact in merged_facts:
            topic = fact.get("topic", "")
            statement = fact.get("statement", "")
            
            if topic == "offerings" and statement:
                # Avoid duplicates
                stmt_lower = statement.lower().strip()
                if stmt_lower and stmt_lower not in seen_items:
                    seen_items.add(stmt_lower)
                    # Check if this looks like a product vs service
                    if any(word in stmt_lower.lower() for word in ["product", "software", "platform", "tool"]):
                        products_list.append({"name": statement})
                    else:
                        services_list.append({"name": statement})
        
        if services_list:
            # Dedupe and limit
            unique_services = []
            seen_svc = set()
            for s in services_list:
                name = s.get("name", "").strip()
                if name and name not in seen_svc:
                    seen_svc.add(name)
                    unique_services.append(s)
            context["services"] = unique_services[:10]
        
        if products_list:
            unique_products = []
            seen_prod = set()
            for p in products_list:
                name = p.get("name", "").strip()
                if name and name not in seen_prod:
                    seen_prod.add(name)
                    unique_products.append(p)
            context["products"] = unique_products[:10]
        
        direct_products = cls._extract_products_from_pages(pages)
        if direct_products:
            existing = context.get("products", [])
            seen_names = {p.get("name", "").lower() for p in existing}
            for prod in direct_products:
                name = prod.get("name", "").strip()
                if name and name.lower() not in seen_names:
                    existing.append(prod)
                    seen_names.add(name.lower())
            context["products"] = existing[:15]

        context["website_pages"] = website_pages
        context["website_crawl"] = {
            "source": source_url,
            "page_count": len(pages),
        }

        next_steps = context.get("next_steps") if isinstance(context.get("next_steps"), list) else []
        for goal in tenant.cta_goals or []:
            label = cls._cta_label(goal)
            if label and label not in next_steps:
                next_steps.append(label)
        if next_steps:
            context["next_steps"] = next_steps[:5]

        return context

    @classmethod
    def _update_crawl_progress(cls, db: Session, tenant: Tenant, percent: int, stage: str) -> None:
        """Update crawl progress percentage and current stage for admin dashboard"""
        tenant.crawl_progress_percent = str(min(100, max(0, percent)))
        tenant.crawl_progress_stage = stage
        tenant.crawl_progress_updated_at = func.now()
        db.flush()

    @classmethod
    def _deactivate_existing_crawl_documents(cls, db: Session, tenant_id: str) -> None:
        # Get all existing website crawl documents for this tenant
        existing_docs = db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.document_type == "website_page",
            Document.category == "website-crawl",
            Document.is_active == True,
        ).all()
        
        # Delete all vector chunks for these documents first
        doc_ids = [doc.id for doc in existing_docs]
        if doc_ids:
            from app.models import DocumentChunk
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
        
        # Now mark documents as inactive
        db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.document_type == "website_page",
            Document.category == "website-crawl",
            Document.is_active == True,
        ).update({"is_active": False}, synchronize_session=False)
        db.flush()

    @staticmethod
    def _normalize_url(url: str) -> Optional[str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        clean_path = parsed.path or "/"
        if clean_path.lower().endswith("/index.html"):
            clean_path = clean_path[:-11] + "/"
        if clean_path.lower().endswith("/index.htm"):
            clean_path = clean_path[:-10] + "/"

        normalized = parsed._replace(fragment="", query="", path=clean_path).geturl()
        # Keep root slash stable while trimming other trailing slashes
        if normalized.endswith("/") and parsed.path not in ["", "/"]:
            normalized = normalized.rstrip("/")
        return normalized or url

    @classmethod
    def _dedupe_pages(cls, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop duplicate pages by normalized URL and by content signature."""
        unique: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()
        seen_content: Set[str] = set()

        for page in pages:
            norm_url = cls._normalize_url(page.get("url", ""))
            if norm_url in seen_urls:
                continue

            signature = cls._content_signature(page.get("content", ""))
            if signature in seen_content:
                continue

            seen_urls.add(norm_url)
            seen_content.add(signature)
            unique.append(page)

        return unique

    @staticmethod
    def _content_signature(content: str) -> str:
        compressed = " ".join((content or "").split())[:2000]
        return hashlib.sha1(compressed.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalize common mojibake artifacts from crawled pages."""
        raw = (text or "").strip()
        if not raw:
            return ""

        # Try repairing UTF-8 interpreted as latin-1.
        try:
            repaired = raw.encode("latin-1").decode("utf-8")
            # Only accept repaired text if it reduces mojibake markers.
            if repaired.count("â") < raw.count("â"):
                raw = repaired
        except Exception:
            pass

        replacements = {
            "â€“": "-",
            "â€”": "-",
            "â€˜": "'",
            "â€™": "'",
            "â€œ": '"',
            "â€\x9d": '"',
            "Â": "",
        }
        for bad, good in replacements.items():
            raw = raw.replace(bad, good)

        return " ".join(raw.split())

    @staticmethod
    def _extract_contact_info(text: str) -> str:
        """Extract address, phone, email from footer text."""
        if not text:
            return ""

        contact_parts = []

        # US-style addresses (e.g., "123 Main St, City, State 12345" or "City, State 12345")
        address_pattern = r'\b\d+\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl)[\s,]+[\w\s]+(?:,?\s*[A-Z]{2})?\s*\d{5}(?:-\d{4})?\b'
        addresses = re.findall(address_pattern, text, re.IGNORECASE)
        for addr in addresses:
            cleaned = addr.strip()
            if cleaned not in contact_parts:
                contact_parts.append(cleaned)

        # Singapore addresses (enhanced: support Jalan, Tower, Block, etc.)
        sg_address = r'\b(?:\d+[A-Za-z\-#\s,]*)?\s*(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl|jalan|tower|block|crescent|circle|park|walk|close|view|square|terrace|central|mall|centre|boulevard|bukit|serangoon|besar|lim)[\w\s,\-#]*Singapore\s*\d{6}\b'
        sg_addresses = re.findall(sg_address, text, re.IGNORECASE)
        for addr in sg_addresses:
            cleaned = addr.strip()
            if cleaned not in contact_parts:
                contact_parts.append(cleaned)

        # Indian addresses (e.g., "#113-A, Periyar Pathai West, Arumbakkam, Chennai - 600 106")
        in_address = r'#?\d+[\w\s,\-]*,?\s*(?:periyar|neelankarai|thiruvanmiyur|velachery|kodambakkam|mylapore|egmore|annanagar|t-nagar|arumbakkam|ambattur|porur| vadapalani|ashok nagar|chennai|mumbai|delhi|hyderabad|bangalore|pune)[\s\-]*(?:-\s*)?\d{3,6}\b'
        in_addresses = re.findall(in_address, text, re.IGNORECASE)
        for addr in in_addresses:
            cleaned = addr.strip()
            if cleaned not in contact_parts and len(cleaned) > 10:
                contact_parts.append(cleaned)

        # International addresses (city, country format)
        intl_address = r'\b[A-Z][\w\s]+,?\s+[A-Z]{2},?\s+\d{5}\b'
        intl_addresses = re.findall(intl_address, text)
        for addr in intl_addresses:
            cleaned = addr.strip()
            if cleaned not in contact_parts:
                contact_parts.append(cleaned)

        # Phone numbers (various formats)
        phone_patterns = [
            r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # 123-456-7890
            r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',  # (123) 456-7890
            r'\b\+\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # +1 123 456 7890
            r'\b\d{3}[-.\s]\d{4}\b',  # 123-4567
            r'\b\+65\s?\d{4}\s?\d{4}\b',  # Singapore +65 9123 4567
            r'\b0\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b',  # Singapore 6123 4567
            r'\b[89]\d{3}[-.\s]?\d{4}\b',  # Singapore mobile 9123 4567
            r'\b65[-.]\d{4}[-.\d]\d{4}\b',  # 65-9123-4567
            r'\b[6-9]\d{9}\b',  # Indian mobile 10-digit 6xxxxx-xxxxx
            r'\b0[6-9]\d{9}\b',  # Indian with leading 0 06xxxxxxxxx
            r'\b\+91\s?[6-9]\d{9}\b',  # Indian +91 9xxxxxxxxx
        ]
        for pattern in phone_patterns:
            phones = re.findall(pattern, text)
            for phone in phones:
                cleaned = phone.strip()
                if cleaned not in contact_parts:
                    contact_parts.append(cleaned)

        # Email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        for email in emails:
            if email not in contact_parts:
                contact_parts.append(email)

        return " | ".join(contact_parts) if contact_parts else ""

    @classmethod
    def _extract_special_contact_links(cls, soup: BeautifulSoup, base_url: str) -> Dict[str, str]:
        links: Dict[str, str] = {}

        for node in soup.find_all(href=True):
            href = (node.get("href") or "").strip()
            lower = href.lower()
            if lower.startswith("mailto:") and "email" not in links:
                links["email"] = href.replace("mailto:", "", 1)
            elif lower.startswith("tel:") and "phone" not in links:
                links["phone"] = href.replace("tel:", "", 1)
            elif "wa.me/" in lower or "whatsapp" in lower:
                links["whatsapp"] = urljoin(base_url, href)

        for node in soup.find_all(attrs={"onclick": True}):
            onclick = str(node.get("onclick") or "")
            match = re.search(r"https?://wa\.me/\d+", onclick, flags=re.IGNORECASE)
            if match and "whatsapp" not in links:
                links["whatsapp"] = match.group(0)

        return links

    @classmethod
    def _extract_structured_contact(cls, soup: BeautifulSoup) -> Dict[str, str]:
        contact: Dict[str, str] = {}
        
        # First: Extract from JSON-LD structured data
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            objects = payload if isinstance(payload, list) else [payload]
            for item in objects:
                if not isinstance(item, dict):
                    continue
                for candidate in cls._iter_structured_items(item):
                    if not isinstance(candidate, dict):
                        continue
                    email = candidate.get("email")
                    telephone = candidate.get("telephone")
                    address = candidate.get("address")
                    if email and not contact.get("email"):
                        contact["email"] = str(email)
                    if telephone and not contact.get("phone"):
                        contact["phone"] = str(telephone)
                    if isinstance(address, dict) and not contact.get("address"):
                        pieces = [
                            str(address.get("streetAddress") or "").strip(),
                            str(address.get("addressLocality") or "").strip(),
                            str(address.get("postalCode") or "").strip(),
                        ]
                        pretty = ", ".join([p for p in pieces if p])
                        if pretty:
                            contact["address"] = pretty
                    elif isinstance(address, str) and address.strip() and not contact.get("address"):
                        contact["address"] = address.strip()
        
        # Second: Also extract from visible HTML contact info (overrides JSON-LD)
        # This catches addresses shown in footers, contact pages, etc.
        contact_text = ""
        
        # Look for address in footer or contact sections
        for elem in soup.find_all(["div", "span", "p", "li"], class_=lambda x: x and any(w in x.lower() for w in ["contact", "address", "footer", "location"])):
            text = elem.get_text(strip=True)
            if text and any(w in text.lower() for w in ["singapore", "tower", "jalan", "#"]):
                contact_text += text + " "
        
        # Parse address from visible text - look for complete address in list items
        import re
        
        # Look for complete address like "Sim Lim Tower, 10 Jalan Besar, #09-10A, Singapore 208787"
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if re.search(r'Sim\s+Lim\s+Tower.*Jalan.*#\d+.*Singapore.*\d{6}', text, re.IGNORECASE):
                # Clean the address - extract meaningful parts
                # Expected: "Sim Lim Tower, 10 Jalan Besar, #09-10A, Singapore 208787"
                contact["address"] = text
                break
        
        # Fallback: get address from contact section if not found
        if not contact.get("address"):
            for elem in soup.find_all(string=re.compile(r'10\s+Jalan\s+Besar', re.IGNORECASE)):
                parent = elem.find_parent()
                if parent:
                    text = parent.get_text(separator=", ", strip=True)
                    if text and "Singapore" in text:
                        contact["address"] = text
                        break
        
        return contact

    @classmethod
    def _iter_structured_items(cls, item: Dict[str, Any]):
        yield item
        graph = item.get("@graph")
        if isinstance(graph, list):
            for obj in graph:
                if isinstance(obj, dict):
                    yield obj

    @classmethod
    def _candidate_urls(cls, tenant: Tenant, website_url: str) -> List[str]:
        candidates: List[str] = []
        for value in [website_url, tenant.website_url]:
            if value:
                normalized = cls._normalize_candidate(value)
                if normalized and normalized not in candidates:
                    candidates.append(normalized)

        if tenant.domain:
            for prefix in ["https://", "http://", "https://www."]:
                candidate = cls._normalize_candidate(prefix + tenant.domain)
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

        return candidates

    @classmethod
    def _normalize_candidate(cls, value: str) -> Optional[str]:
        raw = value.strip()
        if not raw:
            return None
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return cls._normalize_url(raw)

    @staticmethod
    def _cta_label(goal: str) -> str:
        mapping = {
            "lead": "Invite the visitor to share their contact details for follow-up.",
            "booking": "Offer a booking or appointment next step when relevant.",
            "quote": "Offer a quote request next step when pricing or scope is discussed.",
            "support": "Offer a support or contact escalation path when operational help is needed.",
        }
        return mapping.get(goal, "")

    @classmethod
    def _extract_business_facts(
        cls,
        title: str,
        description: str,
        headings: List[str],
        content: str,
        url: str,
    ) -> List[Dict[str, str]]:
        text_parts = [title or "", description or ""] + list(headings or [])
        text_parts.append((content or "")[:6000])
        combined = "\n".join([part for part in text_parts if part]).strip()
        if not combined:
            return []

        sentences = re.split(r"(?<=[.!?])\s+|\n+", combined)
        facts: List[Dict[str, str]] = []
        seen_keys: Set[str] = set()
        per_topic_counts: Dict[str, int] = {}

        for sentence in sentences:
            cleaned = cls._clean_text(sentence)
            if len(cleaned) < 18 or len(cleaned) > 260:
                continue
            lowered = cleaned.lower()
            if lowered.startswith(("home", "about", "contact", "services", "products")) and len(cleaned.split()) <= 3:
                continue

            matched_topics = []
            for topic, keywords in cls.FACT_TOPIC_KEYWORDS.items():
                if any(keyword in lowered for keyword in keywords):
                    matched_topics.append(topic)

            if not matched_topics:
                continue

            for topic in matched_topics[:2]:
                if per_topic_counts.get(topic, 0) >= 4:
                    continue
                key = f"{topic}:{lowered}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                per_topic_counts[topic] = per_topic_counts.get(topic, 0) + 1
                facts.append({
                    "topic": topic,
                    "statement": cleaned,
                    "source_url": url,
                    "title": title[:255] if title else "",
                })


    @staticmethod
    def _build_completion_note(existing_notes: Optional[str], page_count: int, source_url: str) -> str:
        prefix = existing_notes.strip() if existing_notes else ""
        if page_count:
            suffix = f"Website crawl completed with {page_count} page(s) ingested from {source_url}."
        else:
            suffix = f"Website crawl completed with 0 pages ingested from {source_url}. Check DNS, robots, or site protections."

        if not prefix:
            return suffix

        # Avoid repeating the same completion sentence across multiple crawls.
        existing_parts = [part.strip() for part in prefix.split("|") if part.strip()]
        if suffix in existing_parts:
            return " | ".join(existing_parts)

        existing_parts.append(suffix)
        return " | ".join(existing_parts)
