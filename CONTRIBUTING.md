# Contributing to Scrapper_bot

Thank you for your interest in contributing! We welcome all contributions to make this bot better.

## 🤝 How to Contribute

1.  **Fork the repository**
2.  **Clone the project** to your machine
3.  **Create a new branch** (`git checkout -b feature/amazing-feature`)
4.  **Commit your changes** (`git commit -m 'Add some amazing feature'`)
5.  **Push to the branch** (`git push origin feature/amazing-feature`)
6.  **Open a Pull Request**

## 🧩 Project Structure

The project follows a modular structure:

-   `src/`: Contains the source code.
    -   `scrapers.py`: Logic for fetching and parsing RSS feeds.
    -   `bot.py`: Main bot orchestration and Telegram interactions.
    -   `database.py`: Supabase database operations.
    -   `config.py`: Configuration and constants.
-   `docs/`: Documentation files.
-   `sql/`: Database schema and migration scripts.

## 🛠 Development

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
```

### Running Locally

```bash
python -m src.main
```

## 🧪 Testing

Please ensure your changes do not break existing functionality. We encourage adding tests for new features.

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.
