DESTINATION_SHEET_ID = "1TTu5AagW6kRXVW9pCtKx78C36VVrnddu19X_Vw0MacM"

import os
SHOPIFY_SHOP  = os.environ.get("SHOPIFY_SHOP", "mitolife.myshopify.com")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
TW_SHEET_ID = "1EOhZLTg6Ohy-2NLeu89STnKrdNza75KlMdoPylPI3xQ"

DEST_TABS = {
    "triple_whale": "Master_TripleWhale",
    "shopify": "Shopify_OrderTag",
    "ga4": "GA4_Pages",
    "justuno": "Justuno",
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
