#!/usr/bin/env python3
"""
Mise à jour hebdomadaire automatique — Veille IA Enfants/Adolescents
Fichier cible : veille-ia.html
4 domaines PubMed + section web via flux RSS automatisée.
"""

import os, re, json, time, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
import feedparser
import anthropic as ant

# ── Configuration ────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    sys.exit("❌  Variable ANTHROPIC_API_KEY manquante.")

NCBI_BASE        = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NEWSLETTER_PATH  = "veille-ia.html"
ARTICLES_PER_DOM = 3
NCBI_SLEEP       = 0.5
CLAUDE_SLEEP     = 0.3

TODAY      = datetime.utcnow()
DATE_TO    = TODAY.strftime("%Y/%m/%d")
DATE_FROM  = (TODAY - timedelta(days=7)).strftime("%Y/%m/%d")
WEEK_ID    = f"week-{TODAY.strftime('%Y-%m-%d')}"
WEEK_LABEL = TODAY.strftime("%d/%m")
DATE_LABEL = TODAY.strftime("%d/%m/%Y")
CUTOFF     = TODAY - timedelta(days=7)

HIGH_IMPACT = {
    "JAMA", "Lancet", "N Engl J Med", "Nature", "Science", "BMJ",
    "JAMA Psychiatry", "JAMA Network Open", "Nat Med", "Nat Hum Behav",
    "JAMA Pediatr", "Pediatrics", "J Med Internet Res",
    "Psychol Med", "J Child Psychol Psychiatry", "Dev Psychol",
}

# ── Flux RSS ─────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "https://www.lemonde.fr/pixels/rss_full.xml",          "name": "Le Monde Pixels",          "lang": "fr"},
    {"url": "https://theconversation.com/fr/articles.atom",        "name": "The Conversation FR",       "lang": "fr"},
    {"url": "https://presse.inserm.fr/feed/",                      "name": "Inserm",                    "lang": "fr"},
    {"url": "https://www.cnil.fr/fr/rss.xml",                      "name": "CNIL",                      "lang": "fr"},
    {"url": "https://www.technologyreview.com/feed/",              "name": "MIT Technology Review",     "lang": "en"},
]

# Mots-clés pour filtrer les articles pertinents
KEYWORDS_FR = [
    "enfant", "adolescent", "ado", "jeune", "mineur",
    "intelligence artificielle", "chatbot", "écran", "numérique",
    "réseau social", "tiktok", "instagram", "snapchat",
    "santé mentale", "dépression", "anxiété", "addiction",
    "éducation", "école", "apprentissage",
]
KEYWORDS_EN = [
    "child", "children", "adolescent", "teen", "youth", "minor",
    "artificial intelligence", "chatbot", "screen time",
    "social media", "tiktok", "instagram", "mental health",
    "depression", "anxiety", "addiction", "education",
]

# ── Domaines PubMed ───────────────────────────────────────────────────────────

DOMAINS = [
    {
        "id": "a",
        "title": "🤖 IA &amp; Santé mentale enfants/ados",
        "class": "domain-a",
        "query": (
            '(chatbot[Title/Abstract] OR "artificial intelligence"[Title/Abstract] '
            'OR "large language model"[Title/Abstract] OR "generative AI"[Title/Abstract] '
            'OR "conversational agent"[Title/Abstract]) '
            'AND (child[MeSH Terms] OR adolescent[MeSH Terms] '
            'OR "mental health"[Title/Abstract] OR depression[MeSH Terms] '
            'OR anxiety[MeSH Terms] OR "well-being"[Title/Abstract])'
        ),
    },
    {
        "id": "b",
        "title": "📱 Temps d\'écran &amp; Développement cognitif",
        "class": "domain-b",
        "query": (
            '("screen time"[Title/Abstract] OR "social media"[Title/Abstract] '
            'OR "smartphone"[Title/Abstract] OR "digital media"[Title/Abstract] '
            'OR "video game"[Title/Abstract]) '
            'AND (child[MeSH Terms] OR adolescent[MeSH Terms] '
            'OR "cognitive development"[Title/Abstract] '
            'OR "mental health"[Title/Abstract] OR depression[MeSH Terms] '
            'OR sleep[MeSH Terms] OR "well-being"[Title/Abstract])'
        ),
    },
    {
        "id": "c",
        "title": "🤝 IA Compagnon &amp; Relations parasociales",
        "class": "domain-c",
        "query": (
            '("social robot"[Title/Abstract] OR "companion robot"[Title/Abstract] '
            'OR "AI companion"[Title/Abstract] OR "parasocial"[Title/Abstract] '
            'OR "human-robot interaction"[Title/Abstract] '
            'OR "emotional attachment"[Title/Abstract]) '
            'AND (child[MeSH Terms] OR adolescent[MeSH Terms] '
            'OR youth[Title/Abstract] OR development[Title/Abstract])'
        ),
    },
    {
        "id": "d",
        "title": "🧠 Délestage cognitif &amp; IA en éducation",
        "class": "domain-d",
        "query": (
            '("cognitive offloading"[Title/Abstract] OR "AI in education"[Title/Abstract] '
            'OR "artificial intelligence" education[Title/Abstract] '
            'OR "ChatGPT" education[Title/Abstract] '
            'OR "critical thinking"[Title/Abstract] '
            'OR "generative AI" learning[Title/Abstract]) '
            'AND (student[Title/Abstract] OR child[MeSH Terms] '
            'OR adolescent[MeSH Terms] OR school[Title/Abstract])'
        ),
    },
]

# ── PubMed helpers ────────────────────────────────────────────────────────────

def search_pubmed(query: str, max_results: int = 25) -> list:
    params = {
        "db": "pubmed", "term": query,
        "datetype": "edat",
        "mindate": DATE_FROM, "maxdate": DATE_TO,
        "retmax": max_results, "retmode": "json",
        "sort": "relevance",
    }
    r = requests.get(NCBI_BASE + "esearch.fcgi", params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids: list) -> list:
    if not pmids:
        return []
    params = {
        "db": "pubmed", "id": ",".join(pmids),
        "retmode": "xml", "rettype": "abstract"
    }
    r = requests.get(NCBI_BASE + "efetch.fcgi", params=params, timeout=40)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    articles = []

    for art in root.findall(".//PubmedArticle"):
        medline = art.find("MedlineCitation")
        if medline is None:
            continue
        article_el = medline.find("Article")
        if article_el is None:
            continue

        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        title_el = article_el.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        if not title:
            continue

        abstract_parts = article_el.findall(".//AbstractText")
        abstract = " ".join("".join(a.itertext()) for a in abstract_parts).strip()
        if not abstract:
            continue

        journal_el = article_el.find(".//Journal/Title")
        iso_el     = article_el.find(".//Journal/ISOAbbreviation")
        journal    = (iso_el.text if iso_el is not None else
                      (journal_el.text if journal_el is not None else ""))

        year_el  = article_el.find(".//Journal/JournalIssue/PubDate/Year")
        pub_year = year_el.text if year_el is not None else str(TODAY.year)

        authors = []
        for auth in article_el.findall(".//Author"):
            last = auth.findtext("LastName") or ""
            fore = auth.findtext("Initials") or ""
            if last:
                authors.append(f"{last} {fore}".strip())
        author_str = (", ".join(authors[:3]) + " et al.") if len(authors) > 3 else ", ".join(authors)

        pub_types = [pt.text for pt in article_el.findall(".//PublicationType") if pt.text]
        pt_lower  = [p.lower() for p in pub_types]

        score = 0
        if any("randomized" in p for p in pt_lower):        score += 10
        if any("meta-analysis" in p for p in pt_lower):     score += 10
        if any("systematic review" in p for p in pt_lower): score += 8
        if any("review" in p for p in pt_lower):            score += 4
        if any("clinical trial" in p for p in pt_lower):    score += 6
        if journal in HIGH_IMPACT:                           score += 5

        if any("randomized" in p for p in pt_lower):          type_label = "RCT"
        elif any("meta-analysis" in p for p in pt_lower):     type_label = "Méta-analyse"
        elif any("systematic review" in p for p in pt_lower): type_label = "Revue systématique"
        elif any("review" in p for p in pt_lower):            type_label = "Revue"
        elif any("clinical trial" in p for p in pt_lower):    type_label = "Essai clinique"
        else:                                                   type_label = "Autre"

        articles.append({
            "pmid": pmid, "title": title, "abstract": abstract,
            "authors": author_str, "journal": journal, "pub_year": pub_year,
            "pub_types": pub_types, "type_label": type_label,
            "score": score,
        })

    return articles


# ── RSS helpers ───────────────────────────────────────────────────────────────

def is_relevant(text: str, lang: str) -> bool:
    """Vérifie si un titre/description contient des mots-clés pertinents."""
    text_lower = text.lower()
    keywords = KEYWORDS_FR if lang == "fr" else KEYWORDS_EN
    return any(kw in text_lower for kw in keywords)


def entry_date(entry) -> datetime:
    """Extrait la date d'un item RSS (avec fallback)."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6])
            except Exception:
                pass
    return TODAY  # fallback : inclure si date inconnue


def fetch_web_items(max_per_feed: int = 5) -> list:
    """Récupère et filtre les items RSS de la semaine."""
    items = []
    for feed_cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break
                # Filtre date
                pub_date = entry_date(entry)
                if pub_date < CUTOFF:
                    continue
                # Filtre pertinence
                text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                if not is_relevant(text, feed_cfg["lang"]):
                    continue
                items.append({
                    "title":  entry.get("title", "").strip(),
                    "url":    entry.get("link", ""),
                    "source": feed_cfg["name"],
                    "lang":   feed_cfg["lang"],
                    "summary": entry.get("summary", "")[:500],
                })
                count += 1
            print(f"    📡 {feed_cfg['name']} : {count} item(s) pertinent(s)")
        except Exception as e:
            print(f"    ⚠️  Erreur RSS {feed_cfg['name']} : {e}")

    return items[:12]  # max 12 items au total


# ── Claude API ────────────────────────────────────────────────────────────────

SYSTEM_PUBMED = """Tu es un assistant de veille scientifique pour un Professeur de Médecine (pédopsychiatre) qui écrit un livre grand public intitulé "Votre enfant parle à une machine", sur les effets de l'IA et des écrans sur le développement de l'enfant et de l'adolescent.

Pour chaque article scientifique, génère exactement 4 champs :
- resume : synthèse factuelle (design, population, résultats chiffrés, limites). 2-3 phrases max.
- lien_livre : comment cet article nourrit le livre — quel chapitre ou thème il éclaire. 1-2 phrases.
- argument : le fait ou chiffre clé de cet article qui peut servir d'argument ou d'accroche dans le livre. 1-2 phrases percutantes.
- article_type : exactement un parmi : RCT | Méta-analyse | Revue systématique | Revue | Étude de cohorte | Étude qualitative | Étude observationnelle | Commentaire | Autre

Langue : français. Style : direct, accessible au grand public cultivé, mais scientifiquement rigoureux.
Résultats chiffrés si disponibles dans l'abstract.
Réponds UNIQUEMENT en JSON valide, sans markdown, sans backticks.
Format : {"resume":"...","lien_livre":"...","argument":"...","article_type":"..."}"""

SYSTEM_WEB = """Tu es un assistant de veille pour un Professeur de Médecine (pédopsychiatre) qui écrit un livre sur les effets de l'IA et des écrans sur les enfants et adolescents.

On te donne une liste d'articles web de la semaine. Pour chacun, génère un bullet point court en français :
- Si l'article est en anglais, traduis et résume en français.
- Format : une phrase qui commence par une emoji pertinente, suivie du fait clé ou de l'information principale, avec le nom de la source entre parenthèses.
- Style : factuel, direct, 1-2 lignes max par item.

Réponds UNIQUEMENT en JSON valide.
Format : {"items": ["🔍 ...(Source)", "⚠️ ...(Source)", ...]}"""


def claude_pubmed_summary(article: dict) -> dict | None:
    client = ant.Anthropic(api_key=ANTHROPIC_API_KEY)
    user_content = (
        f"Titre : {article['title']}\n"
        f"Auteurs : {article['authors']}\n"
        f"Journal : {article['journal']} {article['pub_year']}\n"
        f"Types : {', '.join(article['pub_types'])}\n\n"
        f"Abstract :\n{article['abstract'][:3500]}"
    )
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PUBMED,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return None
    except Exception as exc:
        print(f"    ⚠️  Claude error (PMID {article['pmid']}) : {exc}")
        return None


def claude_web_bullets(web_items: list) -> list:
    """Génère les bullets web en un seul appel Claude."""
    if not web_items:
        return []
    client = ant.Anthropic(api_key=ANTHROPIC_API_KEY)
    items_text = "\n\n".join(
        f"[{i+1}] Titre : {it['title']}\nSource : {it['source']} ({it['lang']})\nRésumé : {it['summary']}"
        for i, it in enumerate(web_items)
    )
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=SYSTEM_WEB,
            messages=[{"role": "user", "content": items_text}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
        data = json.loads(raw)
        return data.get("items", [])
    except Exception as exc:
        print(f"    ⚠️  Claude web error : {exc}")
        # Fallback : utiliser les titres bruts
        return [f"🔗 {it['title']} ({it['source']})" for it in web_items]


# ── HTML builders ─────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_article(art: dict, summ: dict) -> str:
    article_type = summ.get("article_type", art["type_label"])
    return (
        f'\n      <div class="article">'
        f'\n        <div class="article-title">'
        f'<a href="https://pubmed.ncbi.nlm.nih.gov/{art["pmid"]}/" target="_blank">'
        f'{_esc(art["title"])}</a></div>'
        f'\n        <div class="article-meta">{_esc(art["authors"])}, '
        f'{_esc(art["journal"])}, {art["pub_year"]} | {article_type}</div>'
        f'\n        <div class="article-body">'
        f'\n          <p><span class="label label-resume">Résumé : </span>'
        f'{_esc(summ.get("resume",""))}</p>'
        f'\n          <p><span class="label label-livre">Lien livre : </span>'
        f'{_esc(summ.get("lien_livre",""))}</p>'
        f'\n          <p><span class="label label-arg">Argument : </span>'
        f'{_esc(summ.get("argument",""))}</p>'
        f'\n        </div>'
        f'\n      </div>'
    )


def html_domain(domain: dict, articles: list, summaries: list) -> str:
    body = "".join(html_article(a, s) for a, s in zip(articles, summaries) if s)
    if not body:
        return ""
    return (
        f'\n    <div class="domain {domain["class"]}">'
        f'\n      <div class="domain-title">{domain["title"]}</div>'
        f'{body}'
        f'\n    </div>'
    )


def html_web_section(bullets: list, web_items: list) -> str:
    """Génère la section web avec liens cliquables."""
    if not bullets:
        return ""
    items_html = ""
    for i, bullet in enumerate(bullets):
        url = web_items[i]["url"] if i < len(web_items) else ""
        bullet_esc = _esc(bullet)
        if url:
            # Rendre le bullet cliquable
            items_html += f'\n          <div class="web-item"><a href="{url}" target="_blank">{bullet_esc}</a></div>'
        else:
            items_html += f'\n          <div class="web-item">{bullet_esc}</div>'

    return (
        f'\n    <div class="domain domain-web">'
        f'\n      <div class="domain-title">🌐 Actualités &amp; Rapports</div>'
        f'\n      <div class="article">'
        f'\n        <div class="web-section">'
        f'\n          <h4>Cette semaine</h4>'
        f'{items_html}'
        f'\n        </div>'
        f'\n      </div>'
        f'\n    </div>'
    )


def html_top3(flat: list) -> str:
    medals = ["🥇", "🥈", "🥉"]
    items = ""
    for i, (art, summ) in enumerate(flat[:3]):
        if not summ:
            continue
        argument = (summ.get("argument", "") or "")[:250]
        items += (
            f'      <div class="top3-item">'
            f'<div class="top3-rank">{medals[i]}</div>'
            f'<div class="top3-text">'
            f'<strong>{_esc(art["title"])}</strong>'
            f'{_esc(argument)}'
            f'</div></div>\n'
        )
    return (
        '    <div class="top3">\n'
        '      <h3>⭐ Top 3 pour le livre</h3>\n'
        f'{items}'
        '    </div>'
    )


def build_week_block(domain_data: list, web_bullets: list, web_items: list) -> str:
    flat = sorted(
        [(art, summ) for _, arts, summs in domain_data
         for art, summ in zip(arts, summs) if summ],
        key=lambda x: x[0]["score"], reverse=True,
    )
    top3       = html_top3(flat)
    domains    = "".join(html_domain(d, a, s) for d, a, s in domain_data)
    web_html   = html_web_section(web_bullets, web_items)
    return (
        f"  <!-- WEEK_CONTENT_START:{WEEK_ID} -->\n"
        f'  <div class="tab-content" id="{WEEK_ID}">\n\n'
        f"{top3}\n{domains}\n{web_html}\n\n"
        f'    <div class="entry-footer">Veille du {DATE_LABEL} • PubMed + Web • Claude</div>\n'
        f"  </div>\n"
        f"  <!-- WEEK_CONTENT_END:{WEEK_ID} -->\n"
    )


# ── Injection dans veille-ia.html ─────────────────────────────────────────────

def inject(week_block: str) -> None:
    with open(NEWSLETTER_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    if WEEK_ID in html:
        print(f"ℹ️  Semaine {WEEK_ID} déjà présente.")
        return

    tab_link = (
        f"    <!-- WEEK_START:{WEEK_ID} -->\n"
        f'    <a href="#{WEEK_ID}" class="tab-link">{WEEK_LABEL}</a>\n'
        f"    <!-- WEEK_HEADER_END:{WEEK_ID} -->"
    )
    html = html.replace("<!-- TABS_HEADER_INSERT -->",
                        f"<!-- TABS_HEADER_INSERT -->\n{tab_link}", 1)
    html = html.replace("<!-- TABS_CONTENT_INSERT -->",
                        f"<!-- TABS_CONTENT_INSERT -->\n{week_block}", 1)

    css_rule = (
        f'    body:has(#{WEEK_ID}:target) a[href="#{WEEK_ID}"] '
        '{ background: var(--bg); color: var(--primary); font-weight: 700; }'
    )
    html = html.replace("  </style>", f"{css_rule}\n  </style>", 1)

    with open(NEWSLETTER_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅  veille-ia.html mis à jour — semaine {WEEK_ID}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"🔍  Veille IA : {DATE_FROM} → {DATE_TO}\n")

    # ── PubMed ──
    domain_data = []
    for domain in DOMAINS:
        print(f"📂  Domaine {domain['id'].upper()} : {domain['title']}")
        try:
            pmids = search_pubmed(domain["query"])
            time.sleep(NCBI_SLEEP)
            print(f"    {len(pmids)} PMID(s)")

            if not pmids:
                domain_data.append((domain, [], []))
                continue

            articles = fetch_articles(pmids[:25])
            time.sleep(NCBI_SLEEP)
            articles.sort(key=lambda a: a["score"], reverse=True)
            selected = articles[:ARTICLES_PER_DOM]
            print(f"    {len(selected)} article(s) sélectionné(s)")

            summaries = []
            for art in selected:
                print(f"    • [{art['type_label']}] {art['title'][:65]}...")
                summaries.append(claude_pubmed_summary(art))
                time.sleep(CLAUDE_SLEEP)

            domain_data.append((domain, selected, summaries))

        except Exception as e:
            print(f"    ⚠️  Erreur domaine {domain['id'].upper()}, ignoré : {e}")
            domain_data.append((domain, [], []))

    # ── RSS Web ──
    print(f"\n🌐  Veille web RSS...")
    web_items = fetch_web_items()
    web_bullets = []
    if web_items:
        print(f"    {len(web_items)} item(s) pertinent(s) trouvé(s) — génération bullets...")
        web_bullets = claude_web_bullets(web_items)
        time.sleep(CLAUDE_SLEEP)
    else:
        print("    Aucun item web pertinent cette semaine.")

    # ── Vérification ──
    total = sum(sum(1 for s in summs if s) for _, _, summs in domain_data)
    if total == 0 and not web_bullets:
        print("\n⚠️  Aucun contenu généré — pas de mise à jour.")
        sys.exit(0)

    print(f"\n📝  {total} résumé(s) PubMed + {len(web_bullets)} bullet(s) web — injection...")
    inject(build_week_block(domain_data, web_bullets, web_items))


if __name__ == "__main__":
    main()
