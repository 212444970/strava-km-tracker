"""
Run this script LOCALLY (not on Railway) to export Garmin tokens.
Railway's shared IP is rate-limited by Garmin, so login must happen locally.

Usage:
    pip install garth
    python garmin_login_local.py

Then upload the generated garmin_tokens_export.json via the Admin panel.
"""
import json
import os
import tempfile


def main():
    try:
        import garth
    except ImportError:
        print("Missing dependency. Run: pip install garth")
        return

    email = input("Garmin email: ").strip()
    password = input("Garmin heslo: ").strip()

    try:
        garth.login(email, password, prompt_mfa=lambda: input("MFA kód (z Garmin aplikace): ").strip())
    except TypeError:
        # Older garth without prompt_mfa support
        try:
            garth.login(email, password)
        except Exception as e:
            msg = str(e)
            if "MFA" in msg or "OTP" in msg or "NEED" in msg:
                otp = input("MFA kód (z Garmin aplikace): ").strip()
                try:
                    garth.login(email, password, otp_code=otp)
                except Exception as e2:
                    print(f"MFA selhalo: {e2}")
                    return
            else:
                print(f"Přihlášení selhalo: {e}")
                return
    except Exception as e:
        print(f"Přihlášení selhalo: {e}")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        garth.save(tmpdir)

        export = {}
        for fname in os.listdir(tmpdir):
            path = os.path.join(tmpdir, fname)
            if os.path.isfile(path):
                with open(path) as f:
                    try:
                        export[fname] = json.load(f)
                    except Exception:
                        pass

    if not export:
        print("Chyba: žádné tokeny nebyly uloženy.")
        return

    output = "garmin_tokens_export.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2)

    print(f"\nHotovo! Tokeny uloženy do: {output}")
    print("Dalsi krok: nahraj tento soubor pres Admin panel na Railway.")


if __name__ == "__main__":
    main()
