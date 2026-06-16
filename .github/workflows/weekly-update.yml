#!/usr/bin/env python3
"""
Mise à jour hebdomadaire automatique — Veille Psy Hebdo
Exécuté chaque lundi via GitHub Actions.

Flux :
  1. Recherche PubMed (eutils) sur 7 jours glissants par domaine
  2. Scoring et sélection des 3 meilleurs articles par domaine
  3. Génération des résumés (Résumé / Apport / Pratique) via Claude API
  4. Injection dans newsletter.html (marqueurs HTML persistants)
  5. Le fichier modifié est commité et poussé par le workflow GHA
"""

import os, re, json, time, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

# ── Configuration ────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    sys.exit("❌  Variable ANTHROPIC_API_KEY manquante.")

NCBI_BASE         = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NEWSLETTER_PATH   = "newsletter.html"
ARTICLES_PER_DOM  = 3
NCBI_SLEEP        = 0.4   # secondes entre appels NCBI (limite = 3/s sans clé)
CLAUDE_SLEEP      = 0.5   # secondes entre appels Claude

TODAY      = datetime.utcnow()
DATE_TO    = TODAY.strftime("%Y/%m/%d")
DATE_FROM  = (TODAY - timedelta(days=7)).strftime("%Y/%m/%d")
WEEK_ID    = f"week-{TODAY.strftime('%Y-%m-%d')}"
WEEK_LABEL = TODAY.strftime("%d/%m")
DATE_LABEL = TODAY.strftime("%d/%m/%Y")

# Journaux haute valeur (bonus de score)
HIGH_IMPACT = {
    "JAMA", "Lancet", "N Engl J Med", "Nature", "Science", "BMJ",
    "JAMA Psychiatry", "JAMA Network Open", "Lancet Psychiatry",
    "Am J Psychiatry", "Mol Psychiatry", "JAMA Pediatr", "Biol Psychiatry",
    "Neuropsychopharmacology", "Transl Psychiatry", "Nat Med",
    "Nat Neurosci", "Psychol Med", "Acta Psychiatr Scand",
}

# Domaines et requêtes PubMed
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
            'OR chatbot[Title/Abstract] OR telehealth[Title/Abstract]) '
            'AND (psychiatry[MeSH Terms] OR "mental health"[Title/Abstract] '
            'OR depression[MeSH Terms] OR anxiety disorders[MeSH Terms] '
            'OR schizophrenia[MeSH Terms])'
        ),
    },
    {
        "id": "b",
        "title": "🎯 TDAH",
        "class": "domain-b",
        "query": (
            '"attention deficit hyperactivity disorder"[MeSH Terms] '
            'AND (child[MeSH Terms] OR adolescent[MeSH Terms] '
            'OR treatment[Title/Abstract] OR diagnosis[Title/Abstract] '
            'OR pharmacotherapy[Title/Abstract] OR neurodevelopment[Title/Abstract])'
        ),
    },
    {
        "id": "c",
        "title": "💊 Psychotropes",
        "class": "domain-c",
        "query": (
            '(antidepressant[Title/Abstract] OR antipsychotic[Title/Abstract] '
            'OR psychopharmacology[MeSH Terms] OR "mood stabilizer"[Title/Abstract] '
            'OR pharmacotherapy[Title/Abstract]) '
            'AND (randomized controlled trial[pt] OR "meta-analysis"[pt] '
            'OR "systematic review"[pt] OR clinical trial[pt])'
        ),
    },
    {
        "id": "d",
        "title": "⚡ TMS &amp; Neuromodulation",
        "class": "domain-d",
        "query": (
            '("transcranial magnetic stimulation"[MeSH Terms] '
            'OR "theta burst"[Title/Abstract] '
            'OR "intermittent theta burst"[Title/Abstract] '
            'OR neuromodulation[Title/Abstract] '
            'OR "deep brain stimulation"[MeSH Terms]) '
            'AND (depression[MeSH Terms] OR psychiatric[Title/Abstract] '
            'OR anxiety[MeSH Terms] OR "obsessive-compulsive"[Title/Abstract])'
        ),
    },
    {
        "id": "e",
        "title": "🔬 Articles Innovants",
        "class": "domain-e",
        "query": (
            '(biomarker[Title/Abstract] OR neuroplasticity[MeSH Terms] '
            'OR neuroinflammation[Title/Abstract] OR epigenetics[MeSH Terms] '
            'OR "novel mechanism"[Title/Abstract] OR genetics[Title/Abstract] '
            'OR "new treatment"[Title/Abstract] OR pharmacogenomics[MeSH Terms]) '
            'AND (psychiatric disorders[MeSH Terms] OR "mental health"[Title/Abstract] '
            'OR depression[MeSH Terms] OR schizophrenia[MeSH Terms] '
            'OR "bipolar disorder"[MeSH Terms] OR autism[MeSH Terms])'
        ),
    },
]


# ── PubMed helpers ───────────────────────────────────────────────────────────

def search_pubmed(query: str, max_results: int = 25) -> list:
    """Retourne une liste de PMIDs récents (filtre sur date d'entrée PubMed)."""
    params = {
        "db": "pubmed",
        "term": query,
        "datetype": "edat",
        "mindate": DATE_FROM,
        "maxdate": DATE_TO,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    r = requests.get(NCBI_BASE + "esearch.fcgi", params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids: list) -> list:
    """Récupère et parse les métadonnées XML de PubMed pour une liste de PMIDs."""
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
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

        # PMID
        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        # Titre
        title_el = article_el.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        if not title:
            continue

        # Abstract (obligatoire)
        abstract_parts = article_el.findall(".//AbstractText")
        abstract = " ".join("".join(a.itertext()) for a in abstract_parts).strip()
        if not abstract:
            continue

        # Journal
        journal_el   = article_el.find(".//Journal/Title")
        iso_el       = article_el.find(".//Journal/ISOAbbreviation")
        journal      = (iso_el.text if iso_el is not None else
                        (journal_el.text if journal_el is not None else ""))

        # Année de publication
        year_el = article_el.find(".//Journal/JournalIssue/PubDate/Year")
        pub_year = year_el.text if year_el is not None else str(TODAY.year)

        # Auteurs
        authors = []
        for auth in article_el.findall(".//Author"):
            last = auth.findtext("LastName") or ""
            fore = auth.findtext("Initials") or ""
            if last:
                authors.append(f"{last} {fore}".strip())
        if len(authors) > 3:
            author_str = ", ".join(authors[:3]) + " et al."
        else:
            author_str = ", ".join(authors)

        # Types de publication
        pub_types = [
            pt.text for pt in article_el.findall(".//PublicationType") if pt.text
        ]
        pt_lower = [p.lower() for p in pub_types]

        # Score de qualité
        score = 0
        if any("randomized" in p for p in pt_lower):      score += 10
        if any("meta-analysis" in p for p in pt_lower):   score += 10
        if any("systematic review" in p for p in pt_lower): score += 8
        if any("review" in p for p in pt_lower):           score += 4
        if any("clinical trial" in p for p in pt_lower):  score += 6
        if journal in HIGH_IMPACT:                         score += 5

        # Label affiché du type
        if any("randomized" in p for p in pt_lower):
            type_label = "RCT"
        elif any("meta-analysis" in p for p in pt_lower):
            type_label = "Méta-analyse"
        elif any("systematic review" in p for p in pt_lower):
            type_label = "Revue systématique"
        elif any("review" in p for p in pt_lower):
            type_label = "Revue"
        elif any("clinical trial" in p for p in pt_lower):
            type_label = "Essai clinique"
        elif any("observational" in p for p in pt_lower):
            type_label = "Étude observationnelle"
        else:
            type_label = "Autre"

        # DOI
        doi = ""
        for eid in art.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        articles.append({
            "pmid":       pmid,
            "title":      title,
            "abstract":   abstract,
            "authors":    author_str,
            "journal":    journal,
            "pub_year":   pub_year,
            "pub_types":  pub_types,
            "type_label": type_label,
            "doi":        doi,
            "score":      score,
        })

    return articles


# ── Claude API ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un assistant de veille scientifique pour un Professeur de Médecine spécialisé en psychiatrie de l'enfant et de l'adolescent (Université Paris-Saclay).

Pour chaque article, génère exactement 4 champs :
- resume : synthèse factuelle (design, population, résultats principaux chiffrés, limites si majeures). 2-3 phrases maximum.
- apport : ce que l'article apporte à la littérature (originalité, niveau de preuve). 1-2 phrases.
- pratique : implication clinique directe pour le psychiatre/pédopsychiatre. 1-2 phrases.
- article_type : exactement un parmi : RCT | Méta-analyse | Revue systématique | Revue | Étude de cohorte | Étude qualitative | Étude observationnelle | Lettre | Autre (préciser)

Règles :
- Langue : français exclusivement.
- Style : direct, précis, clinique. Pas de jargon générique, pas de formules creuses.
- Résultats chiffrés si disponibles dans l'abstract (OR, HR, SMD, p-value, effectif).
- Réponds UNIQUEMENT en JSON valide. Pas de markdown, pas de backticks, pas de texte avant/après.

Format exact (et uniquement ce format) :
{"resume":"...","apport":"...","pratique":"...","article_type":"..."}"""


def claude_summary(article: dict) -> dict | None:
    """Appel Claude API pour générer Résumé / Apport / Pratique."""
    user_content = (
        f"Titre : {article['title']}\n"
        f"Auteurs : {article['authors']}\n"
        f"Journal : {article['journal']} {article['pub_year']}\n"
        f"Types de publication : {', '.join(article['pub_types'])}\n\n"
        f"Abstract :\n{article['abstract'][:3500]}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        return json.loads(raw)
    except Exception as exc:
        print(f"    ⚠️  Claude error (PMID {article['pmid']}) : {exc}")
        return None


# ── HTML builders ────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_article(art: dict, summ: dict) -> str:
    article_type = summ.get("article_type", art["type_label"])
    return f"""
      <div class="article">
        <div class="article-title">{_esc(art['title'])}</div>
        <div class="article-meta">{_esc(art['authors'])}, {_esc(art['journal'])} {art['pub_year']} • {article_type}</div>
        <div class="article-body">
          <p><span class="label">Résumé : </span>{_esc(summ.get('resume',''))}</p>
          <p><span class="label">Apport : </span>{_esc(summ.get('apport',''))}</p>
          <p><span class="label">Pratique : </span>{_esc(summ.get('pratique',''))}</p>
        </div>
        <a class="pubmed-link" href="https://pubmed.ncbi.nlm.nih.gov/{art['pmid']}/" target="_blank">🔗 Voir sur PubMed</a>
      </div>"""


def html_domain(domain: dict, articles: list, summaries: list) -> str:
    body = "".join(
        html_article(a, s)
        for a, s in zip(articles, summaries) if s
    )
    if not body:
        return ""
    return f"""
    <div class="domain {domain['class']}">
      <div class="domain-title">{domain['title']}</div>
      {body}
    </div>"""


def html_top3(all_articles_flat: list) -> str:
    """all_articles_flat = [(article, summary), ...] triés par score décroissant."""
    medals = ["🥇", "🥈", "🥉"]
    items = ""
    for i, (art, summ) in enumerate(all_articles_flat[:3]):
        if not summ:
            continue
        pratique_short = (summ.get("pratique", "") or "")[:250]
        items += (
            f'      <div class="top3-item">'
            f'<div class="top3-rank">{medals[i]}</div>'
            f'<div class="top3-text">'
            f'<strong>{_esc(art["title"])}</strong>'
            f'{_esc(pratique_short)}'
            f'</div></div>\n'
        )
    return (
        '    <div class="top3">\n'
        '      <h3>⭐ Top 3 de la semaine</h3>\n'
        f'{items}'
        '    </div>'
    )


def build_week_block(domain_data: list) -> str:
    """Construit le bloc HTML complet de la semaine."""
    # Aplatir et trier pour le Top 3
    all_flat = sorted(
        [
            (art, summ)
            for _, arts, summs in domain_data
            for art, summ in zip(arts, summs)
            if summ
        ],
        key=lambda x: x[0]["score"],
        reverse=True,
    )

    top3 = html_top3(all_flat)
    domains_html = "".join(
        html_domain(dom, arts, summs)
        for dom, arts, summs in domain_data
    )

    return (
        f"  <!-- WEEK_CONTENT_START:{WEEK_ID} -->\n"
        f'  <div class="tab-content" id="{WEEK_ID}">\n\n'
        f"{top3}\n"
        f"{domains_html}\n\n"
        f'    <div class="footer">Générée le {DATE_LABEL} • PubMed</div>\n'
        f"  </div>\n"
        f"  <!-- WEEK_CONTENT_END:{WEEK_ID} -->\n"
    )


# ── Injection dans newsletter.html ───────────────────────────────────────────

def inject_into_newsletter(week_block: str) -> None:
    with open(NEWSLETTER_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Vérifier que la semaine n'a pas déjà été insérée (idempotence)
    if WEEK_ID in html:
        print(f"ℹ️  Semaine {WEEK_ID} déjà présente — pas de modification.")
        return

    # 1. Tab link (prepend après le marqueur)
    tab_link = (
        f"    <!-- WEEK_START:{WEEK_ID} -->\n"
        f'    <a href="#{WEEK_ID}" class="tab-link">{WEEK_LABEL}</a>\n'
        f"    <!-- WEEK_HEADER_END:{WEEK_ID} -->"
    )
    html = html.replace(
        "<!-- TABS_HEADER_INSERT -->",
        f"<!-- TABS_HEADER_INSERT -->\n{tab_link}",
        1,
    )

    # 2. Contenu de la semaine (prepend après le marqueur)
    html = html.replace(
        "<!-- TABS_CONTENT_INSERT -->",
        f"<!-- TABS_CONTENT_INSERT -->\n{week_block}",
        1,
    )

    # 3. CSS pour l'onglet actif (insérer avant </style>)
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

        # Recherche PubMed
        pmids = search_pubmed(domain["query"])
        time.sleep(NCBI_SLEEP)
        print(f"    {len(pmids)} PMID(s) trouvé(s)")

        if not pmids:
            domain_data.append((domain, [], []))
            continue

        # Fetch métadonnées
        articles = fetch_articles(pmids[:25])
        time.sleep(NCBI_SLEEP)

        # Tri et sélection
        articles.sort(key=lambda a: a["score"], reverse=True)
        selected = articles[:ARTICLES_PER_DOM]
        print(f"    {len(selected)} article(s) sélectionné(s)")

        # Génération des résumés
        summaries = []
        for art in selected:
            print(f"    • [{art['type_label']}] {art['title'][:70]}...")
            s = claude_summary(art)
            summaries.append(s)
            time.sleep(CLAUDE_SLEEP)

        domain_data.append((domain, selected, summaries))

    # Vérification
    total = sum(
        sum(1 for s in summs if s)
        for _, _, summs in domain_data
    )
    if total == 0:
        print("\n⚠️  Aucun article résumé généré — pas de mise à jour.")
        sys.exit(0)

    print(f"\n📝  {total} résumé(s) générés — injection dans newsletter.html")
    week_block = build_week_block(domain_data)
    inject_into_newsletter(week_block)


if __name__ == "__main__":
    main()
