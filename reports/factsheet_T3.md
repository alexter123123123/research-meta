# Factsheet — Meta's crawlers and news publishers' robots.txt (29 Oct 2026)

Snapshot T3. 1496 news domains, 10000 top-10k control domains. All numbers generated from `metrics_T3.json`. Data: HasData.

**Lead:** 44.1% of 1388 news sites (95% CI 41.5–46.7%) explicitly block `meta-externalagent` in robots.txt as of 29 Oct 2026, versus 8.9% of the top-10k general sites (n=7122).

## Top 8 stats

1. **Ads gap: 98.2% (601/612; 95% CI 96.8–99.0%) of news sites that FULL_BLOCK `meta-externalagent` in robots.txt do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 601/612)  
   _In plain English:_ This share of publishers blocking the crawler Meta's documentation describes for AI training still leaves its advertising/business crawler open in robots.txt.
2. **Among major (Tier A) news brands that FULL_BLOCK `meta-externalagent` in robots.txt, 100.0% (50/50; 95% CI 92.9–100.0%) do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 50/50)  
   _In plain English:_ Not one of the 50 major news brands that block the crawler Meta's documentation describes for AI training also blocks the one it describes for advertising.
3. **44.1% (612/1388; 95% CI 41.5–46.7%) of news sites FULL_BLOCK `meta-externalagent` in robots.txt.** (n = 612/1388)  
   _In plain English:_ This is the share of news sites whose robots.txt asks the crawler Meta's documentation describes for AI training to stay out entirely.
4. **News sites block `meta-externalagent` in robots.txt 35.2 percentage points more often than top-10k general sites (44.1%, 612/1388 vs 8.9%, 631/7122; difference 95% CI 32.6 to 37.9 pp, Newcombe).** (n = 612/1388)  
   _In plain English:_ News sites are 5.0 times as likely as popular websites in general to block the crawler Meta's documentation describes for AI training.
5. **Meta gap: 12.3% (84/685; 95% CI 10.0–14.9%) of news sites that FULL_BLOCK at least one of gptbot, claudebot, google-extended or ccbot do not FULL_BLOCK `meta-externalagent`.** (n = 84/685)  
   _In plain English:_ This share of publishers blocking other AI companies' training crawlers does not block Meta's.
6. **47.2% (274/581; 95% CI 43.1–51.2%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalagent` in robots.txt.** (n = 274/581)  
   _In plain English:_ Among sites with public signs of using Meta's business tools, this share does not block the crawler Meta's documentation describes for AI training in robots.txt.
7. **100.0% (581/581; 95% CI 99.3–100.0%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 581/581)  
   _In plain English:_ Among sites with public signs of using Meta's business tools, this share leaves Meta's advertising/business crawler unblocked.
8. **18.3% (24/131) of news sites with robots.txt at both T1 and T3 changed any Meta crawler rule (15 publisher-authored, 8 via Cloudflare-managed rules).** (n = 24/131)  
   _In plain English:_ This is how many publishers changed their Meta rules since the story broke.

## Charts

- C1 — % FULL_BLOCK per crawler (Meta vs peers), news vs control — `charts_T3/C1_block_rates.png` / `.svg`
- C2 — daily Meta-related robots.txt changes, 1 Sep → today, with event markers (per press reports) — `charts_T3/C2_timeline.png` / `.svg`
- C3 — exposure funnel: panel → reachable → signals of Meta business-tool use → not blocking — `charts_T3/C3_exposure_funnel.png` / `.svg`
- C4 — the 'ads gap' (blocks meta-externalagent, not meta-externalads) — `charts_T3/C4_ads_gap.png` / `.svg`
- C5 — tier / country breakdown — `charts_T3/C5_tier_country.png` / `.svg`
- C6 — owner-group heatmap (Tier B, groups with n≥10) — `charts_T3/C6_owner_heatmap.png` / `.svg`

## What we did NOT measure

- Whether Meta (or anyone) actually obeys robots.txt — we read the rules, we did not test crawler behaviour or firewalls.
- Whether any site has a business relationship with Meta or is covered by its terms — we only see public signals of Meta business-tool use.
- Paywalls, logins, WAF/CDN bot rules or server-side blocking.
- Sites' robots.txt as seen from outside the US (one fetch location).
- Any legal question.

## Right of reply

Meta was asked for comment on [date]. [Response / no response by publication.]

## Contact

Spokesperson: Roman Milyushkevich, Co-founder and CTO at HasData
