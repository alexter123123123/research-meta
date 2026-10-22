# Factsheet — Meta's crawlers and news publishers' robots.txt (20 Oct 2026)

Snapshot T2. 1496 news domains, 10000 top-10k control domains. All numbers generated from `metrics_T2.json`. Data: HasData.

**Lead:** 40.5% of 1384 news sites (95% CI 38.0–43.1%) explicitly block `meta-externalagent` in robots.txt as of 20 Oct 2026, versus 6.9% of the top-10k general sites (n=7169).

## Top 8 stats

1. **Ads gap: 98.0% (550/561; 95% CI 96.5–98.9%) of news sites that FULL_BLOCK `meta-externalagent` in robots.txt do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 550/561)  
   _In plain English:_ This share of publishers blocking the crawler Meta's documentation describes for AI training still leaves its advertising/business crawler open in robots.txt.
2. **Among major (Tier A) news brands that FULL_BLOCK `meta-externalagent` in robots.txt, 100.0% (48/48; 95% CI 92.6–100.0%) do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 48/48)  
   _In plain English:_ Not one of the 48 major news brands that block the crawler Meta's documentation describes for AI training also blocks the one it describes for advertising.
3. **40.5% (561/1384; 95% CI 38.0–43.1%) of news sites FULL_BLOCK `meta-externalagent` in robots.txt.** (n = 561/1384)  
   _In plain English:_ This is the share of news sites whose robots.txt asks the crawler Meta's documentation describes for AI training to stay out entirely.
4. **News sites block `meta-externalagent` in robots.txt 33.6 percentage points more often than top-10k general sites (40.5%, 561/1384 vs 6.9%, 498/7169; difference 95% CI 31.0 to 36.3 pp, Newcombe).** (n = 561/1384)  
   _In plain English:_ News sites are 5.8 times as likely as popular websites in general to block the crawler Meta's documentation describes for AI training.
5. **Meta gap: 15.2% (99/650; 95% CI 12.7–18.2%) of news sites that FULL_BLOCK at least one of gptbot, claudebot, google-extended or ccbot do not FULL_BLOCK `meta-externalagent`.** (n = 99/650)  
   _In plain English:_ This share of publishers blocking other AI companies' training crawlers does not block Meta's.
6. **50.2% (294/586; 95% CI 46.1–54.2%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalagent` in robots.txt.** (n = 294/586)  
   _In plain English:_ Among sites with public signs of using Meta's business tools, this share does not block the crawler Meta's documentation describes for AI training in robots.txt.
7. **100.0% (586/586; 95% CI 99.3–100.0%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalads`, the crawler Meta describes for advertising and business products.** (n = 586/586)  
   _In plain English:_ Among sites with public signs of using Meta's business tools, this share leaves Meta's advertising/business crawler unblocked.
8. **11.5% (15/131) of news sites with robots.txt at both T1 and T2 changed any Meta crawler rule (12 publisher-authored, 2 via Cloudflare-managed rules).** (n = 15/131)  
   _In plain English:_ This is how many publishers changed their Meta rules since the story broke.

## Charts

- C1 — % FULL_BLOCK per crawler (Meta vs peers), news vs control — `charts/C1_block_rates.png` / `.svg`
- C2 — daily Meta-related robots.txt changes, 1 Sep → today, with event markers (per press reports) — `charts/C2_timeline.png` / `.svg`
- C3 — exposure funnel: panel → reachable → signals of Meta business-tool use → not blocking — `charts/C3_exposure_funnel.png` / `.svg`
- C4 — the 'ads gap' (blocks meta-externalagent, not meta-externalads) — `charts/C4_ads_gap.png` / `.svg`
- C5 — tier / country breakdown — `charts/C5_tier_country.png` / `.svg`
- C6 — owner-group heatmap (Tier B, groups with n≥10) — `charts/C6_owner_heatmap.png` / `.svg`

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
