"""01_quickstart.py — Zero-device public catalog search and product ingestion (no auth needed)."""
from openyamarket import IOSClient, AndroidClient, Device

def main():
    # 1. Initialize iOS or Android client (zero physical device needed)
    client = IOSClient()  # Uses iPhone identity & AppStore headers
    print(f"Device: {client.device.model} ({client.device.platform}), UA: {client.device.user_agent()}")

    # 2. Check live feature toggles and region
    toggles = client.get_toggles()
    print(f"Live FAPI toggles: {len(toggles.get('results', []))} items")

    region = client.resolve_region(213)  # 213 = Москва
    print(f"Region 213: {region['collections']['region']['213'].get('name')}")

    # 3. Explore root catalog & category
    catalog = client.catalog()
    print("Catalog screen loaded:", not catalog.get("_broken"))

    # 4. Search products with automatic client-side parsing (price, sku, title)
    query = "PlayStation 5"
    print(f"\nSearching for '{query}'...")
    products = client.search_products(query, min_price=40000, max_price=150000)
    for p in products[:5]:
        print(f" - [{p['sku']}] {p['title']} -> {p['price']:,} ₽")

    # 5. Fetch full product card screen
    if products:
        sku = products[0]["sku"]
        card = client.product(sku)
        print(f"\nProduct card for SKU {sku} loaded: broken={card.get('_broken')}")

if __name__ == "__main__":
    main()
