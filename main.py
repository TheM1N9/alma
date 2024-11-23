import tweepy
import time
import logging
from datetime import datetime
import json


class TwitterBot:
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

    def post_tweet(self, text):
        """Post a tweet"""
        try:
            tweet = self.client.create_tweet(text=text)
            logging.info(f"Posted tweet: {text}")
            return tweet
        except Exception as e:
            logging.error(f"Error posting tweet: {str(e)}")
            return None

    def read_timeline(self, count=10):
        """Read recent tweets from home timeline"""
        try:
            tweets = self.client.get_home_timeline(max_results=count)
            return [
                (tweet.data["author_id"], tweet.data["text"]) for tweet in tweets.data
            ]
        except Exception as e:
            logging.error(f"Error reading timeline: {str(e)}")
            return []

    def search_tweets(self, query, count=10):
        """Search for tweets matching a query"""
        try:
            tweets = self.client.search_recent_tweets(query=query, max_results=count)
            return [
                (tweet.data["author_id"], tweet.data["text"]) for tweet in tweets.data
            ]
        except Exception as e:
            logging.error(f"Error searching tweets: {str(e)}")
            return []

    def get_user(self, username):
        """Get user details by username"""
        try:
            user = self.client.get_user(username=username)
            if user.data:
                logging.info(f"Found user: {username} (ID: {user.data.id})")
                return user.data
            return None
        except Exception as e:
            logging.error(f"Error getting user details: {str(e)}")
            return None

    def follow_user(self, user_identifier):
        """
        Follow a user using their username or user ID
        Args:
            user_identifier: Can be either a username (str) or user ID (int)
        """
        try:
            # If user_identifier is a string, assume it's a username and get the ID
            if isinstance(user_identifier, str):
                user = self.get_user(user_identifier)
                if not user:
                    logging.error(f"Could not find user: {user_identifier}")
                    return False
                user_id = user.id
            else:
                user_id = user_identifier

            self.client.follow_user(user_id)
            logging.info(f"Followed user ID: {user_id}")
            return True
        except Exception as e:
            logging.error(f"Error following user: {str(e)}")
            return False


# Example usage
if __name__ == "__main__":
    # Load credentials from config file
    with open("config.json") as f:
        config = json.load(f)

    bot = TwitterBot(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        access_token=config["access_token"],
        access_token_secret=config["access_token_secret"],
    )

    # Post a tweet
    bot.post_tweet("Hello, Twitter! I'm a bot.")
    print("Tweet posted successfully")
    # Read recent tweets
    # timeline = bot.read_timeline(5)
    # for username, tweet in timeline:
    #     print(f"{username}: {tweet}")

    # Search for tweets
    # results = bot.search_tweets("#python", 5)
    # for username, tweet in results:
    #     print(f"{username}: {tweet}")

    # Example of following a user by username
    bot.follow_user("elonmusk")  # Now works with username directly
