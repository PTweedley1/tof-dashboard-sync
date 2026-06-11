import json


def load():
    with open("campaigns.json") as f:
        return json.load(f)["campaigns"]


def all_urls():
    """All tracked URLs across every active campaign."""
    return [url for c in load() for url in c.get("urls", [])]


def all_tw_campaigns():
    """All Triple Whale campaign names across every active campaign."""
    return [name for c in load() for name in c.get("triple_whale_campaigns", [])]


def campaign_for_url(url):
    """Return the campaign name that owns a given URL."""
    for c in load():
        if url in c.get("urls", []):
            return c["name"]
    return "Unknown"


def campaign_for_tw(tw_name):
    """Return the campaign name that owns a given Triple Whale campaign."""
    for c in load():
        if tw_name in c.get("triple_whale_campaigns", []):
            return c["name"]
    return "Unknown"
