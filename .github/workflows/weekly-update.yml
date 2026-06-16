name: Veille Psy — Mise à jour hebdomadaire

on:
  schedule:
    # Lundi 7h UTC = 9h Paris (CEST été) / 8h (CET hiver)
    - cron: '0 7 * * 1'
  workflow_dispatch:   # Déclenchement manuel possible depuis l'onglet Actions

jobs:
  update-newsletter:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # Nécessaire pour le git push

    steps:
      - name: Checkout dépôt
        uses: actions/checkout@v4

      - name: Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Installer dépendances
        run: pip install requests anthropic

      - name: Lancer la mise à jour
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python scripts/update_newsletter.py

      - name: Commit & push
        run: |
          git config user.name  "veille-psy-bot"
          git config user.email "bot@veille-psy.local"
          git add newsletter.html
          git diff --staged --quiet && echo "Rien à commiter" || \
            git commit -m "Veille automatique du $(date +'%d/%m/%Y')" && git push
