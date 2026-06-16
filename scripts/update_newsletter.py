#!/usr/bin/env python3
"""
Mise à jour hebdomadaire automatique — Veille Psy Hebdo
"""

import os, re, json, time, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
import anthropic as ant

# ── Configuration ────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    sys.exit("❌  Variable ANTHROPIC_API_KEY manquante.")

NCBI_BASE        = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NEWSLETTER_PATH  = "newsletter.html"
ARTICLES_PER_DOM = 3
NCBI_SLEEP       = 0.5
CLAUDE_SLEEP     = 0.3

TODAY      = datetime.utcnow()
DATE_TO    = TODAY.strftime("%Y/%m/%d")
DATE_FROM  = (TODAY - timedelta(days=7)).strftime("%Y/%m/%d")
WEEK_ID    = f"week-{TODAY.strftime('%Y-%m-%d')}"
WEEK_LABEL = TODAY.strftime("%d/%m")
DATE_LABEL = TODAY.strftime("%d/%m/%Y")

HIGH_IMPACT = {
    "JAMA", "Lancet", "N Engl J Med", "Nature", "Science", "BMJ",
    "JAMA Psychiatry", "JAMA Network Open", "Lancet Psychiatry",
    "Am J Psychiatry", "Mol Psychiatry", "JAMA Pediatr", "Biol Psychiatry",
    "Neuropsychopharmacology", "Transl Psychiatry", "Nat Med", "Nat Neurosci",
    "Psychol Med", "Acta Psychiatr Scand", "J Child Psychol Psychiatry",
}

DOMAINS = [
    {
        "id": "a",
        "title": "📱 Psychiatrie &amp; Numérique",
        "class": "domain-a",
        "query": (
            '(digital health[Title/Abstract] OR smartphone[Title/Abstract] '
            'OR "artificial intelligence"[Title/Abstract] '
            'OR "machine learning"[Title/Abstract] '
            'OR "digital therapeutics"[Title/Abstract] '
            'OR chatbot[Title/Abstract] OR telehealth[Title/Abstract] '
            'OR "large language model"[Title/Abstract]) '
            'AND (psychiatry[MeSH Terms] OR "mental health"[Title/Abstract] '
            'OR depression[MeSH Terms] OR anxiety[MeSH Terms])'
        ),
    },
    {
        "id": "b",
        "title": "🎯 TDAH",
        "class": "domain-b",
        "query": (
            '(ADHD[Title/Abstract] OR "attention deficit"[Title/Abstract] '
            'OR "attention-deficit"[Title/Abstract] '
            'OR "hyperactivity disorder"[Title/Abstract] '
            'OR methylphenidate[Title/Abstract] '
            'OR "attention deficit hyperactivity"[Title/Abstract])'
        ),
    },
    {
        "id": "c",
        "title": "💊 Psychotropes",
        "class": "domain-c",
        "query": (
            '(antidepressant[Title/Abstract] OR antipsychotic[Title/Abstract] '
            'OR psychopharmacology[MeSH Terms] OR "mood stabilizer"[Title/Abstract] '
            'OR ketamine[Title/Abstract] OR esketamine[Title/Abstract]) '
            'AND (randomized controlled trial[pt] OR meta-analysis[pt] '
            'OR systematic review[pt] OR clinical trial[pt])'
        ),
    },
    {
        "id": "d",
        "title": "⚡ TMS &amp; Neuromodulation",
        "class": "domain-d",
        "query": (
            '("transcranial magnetic stimulation"[Title/Abstract] '
            'OR "theta burst"[Title/Abstract] '
            'OR "TMS"[Title/Abstract] '
            'OR neuromodulation[Title/Abstract] '
            'OR "deep brain stimulation"[Title/Abstract] '
            'OR "tDCS"[Title/Abstract]) '
            'AND (depression[MeSH Terms] OR psychiatric[Title/Abstract] '
            'OR anxiety[Title/Abstract] OR "obsessive-compulsive"[Title/Abstract])'
        ),
    },
    {
        "id": "e",
        "title": "🔬 Articles Innovants",
        "class": "domain-e",
        "query": (
            '(biomarker[Title/Abstract] OR neuroplasticity[Title/Abstract] '
            'OR neuroinflammation[Title/Abstract] OR epigenetics[Title/Abstract] '
            'OR "novel"[Title/Abstract] OR pharmacogenomics[Title/Abstract] '
            'OR "gut microbiome"[Title/Abstract] OR proteomics[Title/Abstract]) '
            'AND (psychiatric[Title/Abstract] OR "mental health"[Title/Abstract] '
            'OR depression[MeSH Terms] OR schizophrenia[MeSH Terms] '
            'OR autism[Title/Abstract] OR bipolar[Title/Abstract])'
        ),
    },
]


# ── PubMed helpers ───────────────────────────────────────────────────────────

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

        if any("randomized" in p for p in pt_lower):         type_label = "RCT"
        elif any("meta-analysis" in p for p in pt_lower):    type_label = "Méta-analyse"
        elif any("systematic review" in p for p in pt_lower): type_label = "Revue systématique"
        elif any("review" in p for p in pt_lower):            type_label = "Revue"
        elif any("clinical trial" in p for p in pt_lower):   type_label = "Essai clinique"
        else:                                                  type_label = "Autre"

        doi = ""
        for eid in art.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        articles.append({
            "pmid": pmid, "title": title, "abstract": abstract,
            "authors": author_str, "journal": journal, "pub_year": pub_year,
            "pub_types": pub_types, "type_label": type_label, "doi": doi,
            "score": score,
        })

    return articles


# ── Claude API ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un assistant de veille scientifique pour un Professeur de Médecine spécialisé en psychiatrie de l'enfant et de l'adolescent.

Pour chaque article, génère exactement 4 champs :
- resume : synthèse factuelle (design, population, résultats principaux chiffrés, limites si majeures). 2-3 phrases max.
- apport : ce que l'article apporte à la littérature (originalité, niveau de preuve). 1-2 phrases.
- pratique : implication clinique directe pour le psychiatre/pédopsychiatre. 1-2 phrases.
- article_type : exactement un parmi : RCT | Méta-analyse | Revue systématique | Revue | Étude de cohorte | Étude qualitative | Étude observationnelle | Lettre | Autre

Langue : français. Style : direct, précis, clinique. Résultats chiffrés si disponibles.
Réponds UNIQUEMENT en JSON valide, sans markdown, sans backticks.
Format : {"resume":"...","apport":"...","pratique":"...","article_type":"..."}"""


def claude_summary(article: dict) -> dict | None:
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
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        if not message.content or not hasattr(message.content[0], 'text'):
            print(f"    ⚠️  Réponse vide (PMID {article['pmid']})")
            return None
        raw = message.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
        if not raw:
            print(f"    ⚠️  Texte vide (PMID {article['pmid']})")
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            print(f"    ⚠️  JSON non parseable (PMID {article['pmid']}) : {raw[:100]}")
            return None
    except Exception as exc:
        print(f"    ⚠️  Claude error (PMID {article['pmid']}) : {exc}")
        return None


# ── HTML builders ────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_article(art: dict, summ: dict) -> str:
    article_type = summ.get("article_type", art["type_label"])
    return (
        f'\n      <div class="article">'
        f'\n        <div class="article-title">{_esc(art["title"])}</div>'
        f'\n        <div class="article-meta">{_esc(art["authors"])}, {_esc(art["journal"])} {art["pub_year"]} • {article_type}</div>'
        f'\n        <div class="article-body">'
        f'\n          <p><span class="label">Résumé : </span>{_esc(summ.get("resume",""))}</p>'
        f'\n          <p><span class="label">Apport : </span>{_esc(summ.get("apport",""))}</p>'
        f'\n          <p><span class="label">Pratique : </span>{_esc(summ.get("pratique",""))}</p>'
        f'\n        </div>'
        f'\n        <a class="pubmed-link" href="https://pubmed.ncbi.nlm.nih.gov/{art["pmid"]}/" target="_blank">🔗 Voir sur PubMed</a>'
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


def html_top3(flat: list) -> str:
    medals = ["🥇", "🥈", "🥉"]
    items = ""
    for i, (art, summ) in enumerate(flat[:3]):
        if not summ:
            continue
        pratique = (summ.get("pratique", "") or "")[:250]
        items += (
            f'      <div class="top3-item">'
            f'<div class="top3-rank">{medals[i]}</div>'
            f'<div class="top3-text"><strong>{_esc(art["title"])}</strong>'
            f'{_esc(pratique)}</div></div>\n'
        )
    return (
        '    <div class="top3">\n'
        '      <h3>⭐ Top 3 de la semaine</h3>\n'
        f'{items}'
        '    </div>'
    )


def build_week_block(domain_data: list) -> str:
    flat = sorted(
        [(art, summ) for _, arts, summs in domain_data
         for art, summ in zip(arts, summs) if summ],
        key=lambda x: x[0]["score"], reverse=True,
    )
    top3    = html_top3(flat)
    domains = "".join(html_domain(d, a, s) for d, a, s in domain_data)
    return (
        f"  <!-- WEEK_CONTENT_START:{WEEK_ID} -->\n"
        f'  <div class="tab-content" id="{WEEK_ID}">\n\n'
        f"{top3}\n{domains}\n\n"
        f'    <div class="footer">Générée le {DATE_LABEL} • PubMed</div>\n'
        f"  </div>\n"
        f"  <!-- WEEK_CONTENT_END:{WEEK_ID} -->\n"
    )


# ── Injection dans newsletter.html ───────────────────────────────────────────

def inject(week_block: str) -> None:
    with open(NEWSLETTER_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    if WEEK_ID in html:
        print(f"ℹ️  Semaine {WEEK_ID} déjà présente — pas de modification.")
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
    print(f"✅  newsletter.html mis à jour — semaine {WEEK_ID}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"🔍  Veille PubMed : {DATE_FROM} → {DATE_TO}\n")
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
                summaries.append(claude_summary(art))
                time.sleep(CLAUDE_SLEEP)

            domain_data.append((domain, selected, summaries))

        except Exception as e:
            print(f"    ⚠️  Erreur domaine {domain['id'].upper()}, ignoré : {e}")
            domain_data.append((domain, [], []))
            continue

    total = sum(sum(1 for s in summs if s) for _, _, summs in domain_data)
    if total == 0:
        print("\n⚠️  Aucun résumé généré — pas de mise à jour.")
        sys.exit(0)

    print(f"\n📝  {total} résumé(s) — injection dans {NEWSLETTER_PATH}")
    inject(build_week_block(domain_data))


if __name__ == "__main__":
    main()
