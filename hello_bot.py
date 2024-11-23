import tweepy
import json
import logging


class SimpleTwitterBot:
    def __init__(self, api_key, api_secret, access_token, access_token_secret):
        """Initialize the Twitter bot with API credentials"""
        # Authenticate with Twitter API v2
        self.client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
        )

        # Setup logging
        logging.basicConfig(
            filename="twitter_bot.log",
            format="%(asctime)s - %(message)s",
            level=logging.INFO,
        )

    def send_hello_world(self):
        """Post 'Hello, World!!' tweet"""
        try:
            tweet = self.client.create_tweet(text="Hakuna Matata")
            logging.info("Successfully posted Hello World tweet!")
            print("Tweet posted successfully!")
            return tweet
        except Exception as e:
            logging.error(f"Error posting tweet: {str(e)}")
            print(f"Error posting tweet: {str(e)}")
            return None


if __name__ == "__main__":
    # Load credentials from config file
    with open("config.json") as f:
        config = json.load(f)

    # print(config)

    # Create bot instance
    bot = SimpleTwitterBot(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        access_token=config["access_token"],
        access_token_secret=config["access_token_secret"],
    )

    # Send the tweet
    bot.send_hello_world()
