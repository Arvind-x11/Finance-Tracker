
from app import app, init_db, current_month


def main():
    init_db()

    with app.test_client() as client:
        response = client.post(
            "/api/recurring/apply",
            json={"month": current_month()}
        )

        print(response.status_code, response.get_data(as_text=True))

        if response.status_code != 200:
            raise RuntimeError("Recurring transactions could not be applied")


if __name__ == "__main__":
    main()