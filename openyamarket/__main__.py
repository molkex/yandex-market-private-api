"""Command-line entry point for openYaMarket / yandex-market-private-api."""
from __future__ import annotations

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="openyamarket",
        description="Yandex Market Private API (Zero-Device, Pure-HTTP, iOS & Android)"
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the interactive web dashboard (requires fastapi & uvicorn)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the web dashboard (default: 8000)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host for the web dashboard (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--search",
        type=str,
        help="Perform a quick search for products"
    )
    parser.add_argument(
        "--product",
        type=str,
        help="Inspect product SKU (stock, pricing, referral rewards)"
    )
    parser.add_argument(
        "--platform",
        choices=["ios", "android"],
        default="ios",
        help="Platform preset (default: ios)"
    )

    args = parser.parse_args()

    if args.web or (len(sys.argv) == 1 and not args.search and not args.product):
        try:
            from .web import app
            import uvicorn
            print(f"🚀 openYaMarket Web Dashboard launching on http://{args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port)
        except ImportError:
            print("Web dependencies not found. Install via: pip install 'yandex-market-private-api[web]'")
            sys.exit(1)
        return

    from .client import AndroidClient, IOSClient
    client = AndroidClient() if args.platform == "android" else IOSClient()

    if args.search:
        print(f"Searching for '{args.search}' [{args.platform.upper()}]...")
        results = client.search_products(args.search, pages=1)
        for i, p in enumerate(results[:10], 1):
            price_str = f"{p.get('price')} ₽" if p.get('price') else "N/A"
            b2b_str = f" | B2B: {p.get('b2b_bonus')} ₽" if p.get('b2b_bonus') else ""
            print(f"{i:2d}. [{p.get('sku')}] {p.get('title')} — {price_str}{b2b_str}")

    elif args.product:
        print(f"Inspecting SKU {args.product} [{args.platform.upper()}]...")
        from .web import _inspect_sku
        data = _inspect_sku(client, args.product)
        print(f"SKU: {data['sku']}")
        print(f"Название: {data['title']}")
        print(f"Цена: {data['price']} ₽" if data.get('price') else "Цена: N/A")
        print(f"Базовая награда: {data.get('promise') or 0} баллов Плюса")
        print(f"B2B-бонус (Самозанятые): {data.get('b2b_bonus') or 0} ₽")
        print(f"Точный остаток: {data.get('stock_amount') if data.get('stock_amount') is not None else 'В наличии'}")
        if data.get('referral_url'):
            print(f"Реф-ссылка: {data['referral_url']}")


if __name__ == "__main__":
    main()
