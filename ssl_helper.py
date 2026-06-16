import os
import sys
import datetime

def generate_self_signed_cert(cert_path="cert.pem", key_path="key.pem"):
    """
    Generates a self-signed certificate and key using cryptography package,
    and writes them to the specified files.
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("[HTTPS Warning] 'cryptography' package is not installed. Trying to install...")
        try:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
        except Exception as e:
            print(f"[HTTPS Error] Failed to install/import 'cryptography' library: {e}")
            return False

    try:
        # Generate private key
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Generate self-signed certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Student Study Buddy"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow() - datetime.timedelta(days=1)
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=3650)  # 10 years validity
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName("127.0.0.1")]),
            critical=False,
        ).sign(key, hashes.SHA256())

        # Write private key
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        # Write certificate
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"[HTTPS] Successfully generated self-signed certificate at '{cert_path}' and key at '{key_path}'.")
        return True
    except Exception as e:
        print(f"[HTTPS Error] Failed to generate self-signed certificate: {e}")
        return False

def get_ssl_context(cert_filename="cert.pem", key_filename="key.pem"):
    """
    Returns a valid tuple (cert_path, key_path) if HTTPS is enabled and certificates are found/generated.
    Returns None if HTTPS is disabled or if certificates cannot be resolved, indicating HTTP fallback.
    """
    # Check if HTTPS is enabled in environment (default to false)
    if os.environ.get('USE_HTTPS', 'false').lower() != 'true':
        return None

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base_dir, cert_filename)
    key_path = os.path.join(base_dir, key_filename)

    # Check if files already exist
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return (cert_path, key_path)

    # Try to generate files
    success = generate_self_signed_cert(cert_path, key_path)
    if success and os.path.exists(cert_path) and os.path.exists(key_path):
        return (cert_path, key_path)

    print("[HTTPS Warning] Running server in insecure HTTP mode.")
    return None
