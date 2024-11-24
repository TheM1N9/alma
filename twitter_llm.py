import asyncio
from twikit import Client
import logging
import google.generativeai as genai
import os
from dotenv import load_dotenv
import tweepy
from datetime import datetime, timezone
import time

load_dotenv()


class SimpleTwitterBot:
    def __init__(self, username, email, password, gemini_api_key, twitter_credentials):
        """Initialize the bot with both twikit and official Twitter API"""
        # Twikit initialization
        self.client = Client("en-US")
        self.username = username
        self.email = email
        self.password = password

        # Twitter API initialization
        auth = tweepy.OAuthHandler(
            twitter_credentials["consumer_key"], twitter_credentials["consumer_secret"]
        )
        auth.set_access_token(
            twitter_credentials["access_token"],
            twitter_credentials["access_token_secret"],
        )
        self.twitter_api = tweepy.API(auth)
        self.twitter_client = tweepy.Client(
            bearer_token=twitter_credentials["bearer_token"],
            consumer_key=twitter_credentials["consumer_key"],
            consumer_secret=twitter_credentials["consumer_secret"],
            access_token=twitter_credentials["access_token"],
            access_token_secret=twitter_credentials["access_token_secret"],
        )

        # Store last checked mention ID
        self.last_mention_id = None

        # Configure Gemini
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

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
            print(f"auth_info_1: {self.username}")
            print(f"auth_info_2: {self.email}")
            print(f"password: {self.password}")
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

    async def get_ai_response(self, tweet_text, author):
        """Generate AI response using Gemini"""
        try:
            prompt = f"""
            You are a friendly Twitter bot. Someone just mentioned you in a tweet.
            Tweet: {tweet_text}
            Author: @{author}
            
            Write a friendly, engaging response in less than 280 characters. 
            Include their @username at the start.
            Be helpful but concise.
            """

            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            logging.error(f"Error generating AI response: {str(e)}")
            return f"@{author} Thanks for reaching out! 👋"

    async def check_mentions(self):
        """Check and respond to mentions using official Twitter API"""
        try:
            # Get mentions timeline
            mentions = self.twitter_api.mentions_timeline(
                since_id=self.last_mention_id, tweet_mode="extended"
            )

            for mention in mentions:
                # Update last mention ID
                if self.last_mention_id is None or mention.id > self.last_mention_id:
                    self.last_mention_id = mention.id

                # Get tweet text and author
                tweet_text = mention.full_text
                author = mention.user.screen_name

                # Get AI-generated response
                response = await self.get_ai_response(tweet_text, author)

                # Reply using twikit
                await self.client.create_tweet(text=response, reply_to=mention.id)

                logging.info(f"Replied to mention from @{author}")
                print(f"Replied to mention from @{author}")

                # Avoid rate limits
                await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"Error checking mentions: {str(e)}")
            print(f"Error checking mentions: {str(e)}")

    async def run_mention_monitor(self, check_interval=60):
        """Continuously monitor mentions"""
        while True:
            # await self.check_mentions()
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

    async def get_topic_thread(self, topic):
        """Generate an informative thread about a trending topic using Gemini"""
        try:
            prompt = f"""
            Create a short, engaging Twitter thread (3-4 tweets) about this trending topic: {topic}
            
            Requirements:
            - Each tweet must be under 280 characters
            - Make it informative and engaging
            - Include relevant context and why it's trending
            - Separate tweets with [TWEET]
            - Don't use hashtags unless they're part of the trend name
            - Be factual and objective
            
            Format your response as tweet-sized chunks separated by [TWEET].
            """

            response = self.model.generate_content(prompt)
            # Split the response into individual tweets
            tweets = response.text.split("[TWEET]")
            # Clean up tweets (remove empty strings and strip whitespace)
            tweets = [tweet.strip() for tweet in tweets if tweet.strip()]
            return tweets

        except Exception as e:
            logging.error(f"Error generating thread content: {str(e)}")
            return [f"🔥 Trending: {topic}", "Stay tuned for updates!"]

    async def post_thread(self, tweets):
        """Post a thread of tweets"""
        try:
            previous_tweet_id = None
            for tweet in tweets:
                if previous_tweet_id:
                    response = await self.client.create_tweet(
                        text=tweet, reply_to=previous_tweet_id
                    )
                else:
                    response = await self.client.create_tweet(text=tweet)
                previous_tweet_id = response.id
                # Small delay to prevent rate limiting
                await asyncio.sleep(2)
            return True
        except Exception as e:
            logging.error(f"Error posting thread: {str(e)}")
            return False

    async def tweet_trending_topics(self):
        """Tweet about current trending topics with informative threads"""
        try:
            trends = await self.get_trending_topics()
            if trends:
                # Take top 3 trending topics
                for trend in trends[:3]:
                    # Generate thread content
                    thread_tweets = await self.get_topic_thread(trend["name"])

                    # Post the thread
                    success = await self.post_thread(thread_tweets)

                    if success:
                        logging.info(
                            f"Successfully posted thread about {trend['name']}"
                        )
                        print(f"Thread posted about: {trend['name']}")

                    # Wait between threads to prevent rate limiting
                    await asyncio.sleep(30)

        except Exception as e:
            logging.error(f"Error posting trending topics: {str(e)}")
            print(f"Error posting trending topics: {str(e)}")

    async def check_dms(self):
        """Check and respond to DMs using twikit"""
        try:
            # Get your user ID first
            my_user_id = await self.client.user_id()
            sender_id = "manikanta918818"

            # Get DM history
            dm_history = await self.client.get_dm_history(user_id=sender_id)

            for message in dm_history:
                try:

                    # Get message text and sender
                    message_text = message.text
                    # sender = message.sender.screen_name

                    # Generate AI response
                    response = await self.get_ai_response_dm(
                        message_text=message_text, sender=sender_id
                    )

                    # Send DM reply
                    await self.client.send_dm(user_id=sender_id, text=response)

                    logging.info(f"Replied to DM from @{sender_id}")
                    print(f"Replied to DM from @{sender_id}")

                    # Avoid rate limits
                    await asyncio.sleep(2)

                except Exception as e:
                    logging.error(f"Error processing individual message: {str(e)}")
                    continue

        except Exception as e:
            logging.error(f"Error checking DMs: {str(e)}")
            print(f"Error checking DMs: {str(e)}")

    async def get_ai_response_dm(self, message_text, sender):
        """Generate AI response for DMs using Gemini"""
        try:
            prompt = f"""
            You are a friendly Twitter bot responding to a direct message.
            Message: {message_text}
            Sender: @{sender}
            
            Write a helpful and friendly response.
            Be more detailed than in public tweets since DMs have no character limit.
            Keep the tone conversational and engaging.
            """

            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            logging.error(f"Error generating DM response: {str(e)}")
            return f"Hi @{sender}! Thanks for your message. I'm experiencing some technical difficulties right now, but I'll get back to you soon!"

    async def run_dm_monitor(self, check_interval=60):
        """Continuously monitor DMs"""
        while True:
            await self.check_dms()
            await asyncio.sleep(check_interval)  # Wait for specified interval


async def main():
    # Twitter API credentials
    twitter_credentials = {
        "consumer_key": os.getenv("TWITTER_CONSUMER_KEY"),
        "consumer_secret": os.getenv("TWITTER_CONSUMER_SECRET"),
        "access_token": os.getenv("TWITTER_ACCESS_TOKEN"),
        "access_token_secret": os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
        "bearer_token": os.getenv("TWITTER_BEARER_TOKEN"),
    }

    # Create bot instance
    bot = SimpleTwitterBot(
        username=os.getenv("USER_NAME"),
        email=os.getenv("EMAIL"),
        password=os.getenv("PASSWORD"),
        gemini_api_key=os.getenv("GOOGLE_API_KEY"),
        twitter_credentials=twitter_credentials,
    )

    try:
        await bot.login()
        # await bot.tweet_trending_topics()
        await bot.run_dm_monitor()
    except Exception as e:
        print(f"Error during execution: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
