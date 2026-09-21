"""04_headless_registration.py — Zero-device registration pipeline with SMS provider."""
from openyamarket import Device, IOSClient
from openyamarket.passport import Passport

PHONE = "+7XXXXXXXXXX"  # Replace with phone number you control

def sms_input():
    return input("Enter 6-digit SMS code: ").strip()

def main():
    device = Device.ios()
    print(f"Initiating headless registration for {PHONE} on {device.model} ({device.platform})...")

    pp = Passport.ios(device)
    # Full automated pipeline: start -> send_sms -> confirm_sms -> register_neophonish
    # reg = pp.register(PHONE, sms_input, firstname="Ivan", lastname="Petrov")
    # token = reg["access_token"]
    # print(f"Successfully registered account! UID: {reg.get('uid')}, Token: {token[:10]}...")

    # client = IOSClient(device=device, oauth_token=token)
    # print("Personal profile:", client.profile().get("_broken"))

if __name__ == "__main__":
    main()
