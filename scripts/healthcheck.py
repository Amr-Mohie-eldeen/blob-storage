# scripts/healthcheck.py
import sys

import requests


def check_service(service_type, port):
    try:
        response = requests.get(f"http://localhost:{port}/health")
        if response.status_code == 200:
            print(f"{service_type} is healthy")
            return 0
        else:
            print(f"{service_type} is not healthy")
            return 1
    except:
        print(f"Cannot connect to {service_type}")
        return 1


if __name__ == "__main__":
    service_type = sys.argv[1]
    port = int(sys.argv[2])
    sys.exit(check_service(service_type, port))
