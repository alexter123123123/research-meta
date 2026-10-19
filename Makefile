.PHONY: all test panel t2 wayback parse report site

all:
	mcs all --snapshot T2

test:
	pytest -q

panel:
	mcs build-panel

t2:
	mcs fetch-live --label T2 --with-signals
	mcs render

wayback:
	mcs fetch-wayback-history --from 2026-09-01 --panel news
	mcs fetch-wayback-homepages
	mcs meta-docs-history
	mcs fetch-wayback-history --from 2026-09-01 --panel control

parse:
	mcs parse
	mcs signals

report:
	mcs analyze --snapshot T2
	mcs report --snapshot T2
	mcs site
