"""02_referral_radar.py — Extract live referral reward promises (standard & B2B/self-employed bonus)."""
from openyamarket import IOSClient

# Requires a valid Yandex OAuth token (obtained via Passport or app login)
OAUTH_TOKEN = "AQAAAAA..."

def main():
    client = IOSClient(oauth_token=OAUTH_TOKEN)
    
    # Target SKU (e.g. PlayStation 5 Pro)
    target_sku = "6257253212"
    
    print(f"Fetching referral context for SKU {target_sku}...")
    try:
        ref = client.referral_share(target_sku)
        print("\n--- Referral Share Information ---")
        print(f"Base Reward (руб.):       {ref.get('bonus')} ₽")
        print(f"B2B Reward (Самозанятые): {ref.get('b2b_bonus')} ₽")
        print(f"Referral URL:             {ref.get('referral_url')}")
        print(f"Public ID:                {ref.get('public_id')}")
    except Exception as e:
        print("Note: referral_share requires an authenticated account. Error:", e)

if __name__ == "__main__":
    main()
