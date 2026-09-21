"""03_cart_and_favorites.py — Manage cart and wishlist items via mobile RemoteAction engine."""
from openyamarket import AndroidClient

OAUTH_TOKEN = "AQAAAAA..."

def main():
    client = AndroidClient(oauth_token=OAUTH_TOKEN)

    sku = "6256889761"

    # Add to cart
    print(f"Adding SKU {sku} to cart...")
    # res = client.add_to_cart(sku)

    # View cart
    cart_data = client.cart()
    print("Cart screen loaded:", not cart_data.get("_broken"))

    # Wishlist operations
    # client.add_to_favourites(sku)
    # favs = client.favourites()
    # client.remove_from_favourites(sku)

if __name__ == "__main__":
    main()
