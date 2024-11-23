import asyncio
from twikit import Client
import logging


class SimpleTwitterBot:
    def __init__(self, username, email, password):
        """Initialize the Twitter bot with login credentials"""
        self.client = Client(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            language="en-US",
        )
        self.username = username
        self.email = email
        self.password = password

        # Setup logging
        logging.basicConfig(
            filename="twitter_bot.log",
            format="%(asctime)s - %(message)s",
            level=logging.INFO,
        )

    async def login(self):
        """Login to Twitter"""
        try:
            await self.client.login(
                auth_info_1=self.username,
                auth_info_2=self.email,
                password=self.password,
            )
            logging.info("Successfully logged in to Twitter!")
        except Exception as e:
            logging.error(f"Error logging in: {str(e)}")
            raise e

    async def send_hello_world(self):
        """Post 'Hakuna Matata' tweet"""
        try:
            await self.client.create_tweet(text="I'm using Python!!")
            logging.info("Successfully posted Hello World tweet!")
            print("Tweet posted successfully!")
        except Exception as e:
            logging.error(f"Error posting tweet: {str(e)}")
            print(f"Error posting tweet: {str(e)}")

    async def check_mentions(self):
        """Check and respond to mentions"""
        try:
            # Get mentions from the notifications, specifically requesting 'Mentions' type
            notifications = await self.client.get_notifications(type="Mentions")

            # No need to filter again since we specifically requested mentions
            for mention in notifications:
                # Get the tweet text and author
                tweet_text = mention.tweet.text
                author = mention.tweet.user.screen_name

                # Create a response
                response = f"@{author} Don't mention, I'm busy learning!!"

                # Reply to the tweet
                await self.client.create_tweet(text=response, reply_to=mention.tweet.id)
                logging.info(f"Replied to mention from @{author}")
                print(f"Replied to mention from @{author}")

        except Exception as e:
            logging.error(f"Error checking mentions: {str(e)}")
            print(f"Error checking mentions: {str(e)}")

    async def run_mention_monitor(self, check_interval=60):
        """Continuously monitor mentions"""
        while True:
            await self.check_mentions()
            await asyncio.sleep(check_interval)  # Wait for specified interval

    async def get_trending_topics(self):
        """Get current trending topics"""
        try:
            # Get trending topics
            trends = await self.client.get_trends("trending")
            logging.info("Successfully retrieved trending topics")

            # Format and return the trends
            trending_topics = []
            for trend in trends:
                trending_topics.append(
                    {
                        "name": trend.name,
                        "tweet_count": trend.tweets_count,
                        "context": trend.domain_context,
                    }
                )

            return trending_topics

        except Exception as e:
            logging.error(f"Error getting trending topics: {str(e)}")
            print(f"Error getting trending topics: {str(e)}")
            return []

    async def tweet_trending_topics(self):
        """Tweet about current trending topics"""
        try:
            trends = await self.get_trending_topics()
            if trends:
                # Create a tweet with top 5 trending topics
                trend_text = "🔥 Current Trending Topics:\n\n"
                for i, trend in enumerate(trends[:5], 1):
                    trend_text += f"{i}. {trend['name']}\n"

                await self.client.create_tweet(text=trend_text)
                logging.info("Successfully posted trending topics tweet")
                print("Trending topics tweet posted!")

        except Exception as e:
            logging.error(f"Error posting trending topics: {str(e)}")
            print(f"Error posting trending topics: {str(e)}")


async def main():
    # Create bot instance with login credentials
    bot = SimpleTwitterBot(
        username="manikanta918818",
        email="manikantakakarla27@gmail.com",
        password="Alma@2311",
    )

    # Start both the hello world tweet and mention monitoring
    await bot.login()
    # await bot.tweet_trending_topics()

    # Continue with mention monitoring
    await bot.run_mention_monitor()


if __name__ == "__main__":
    asyncio.run(main())
