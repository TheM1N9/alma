import os
import random
import re
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
import google.generativeai as genai
import logging
from typing import List, Dict, Any
import email.utils
from datetime import datetime, timezone
import json
from twikit import Client
import asyncio


class GmailMonitor:
    def __init__(self, check_interval: int = 60):
        """Initialize Gmail Monitor with improved logging and tracking"""
        self.SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        self.check_interval = check_interval
        self.service = None
        self.start_time = datetime.now(timezone.utc)

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("gmail_monitor.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Initialize empty list for processed messages
        self.processed_messages = []

        # Add Twitter credentials
        self.twitter_client = None
        self.twitter_username = os.getenv("USER_NAME", "")
        self.twitter_email = os.getenv("EMAIL", "")
        self.twitter_password = os.getenv("PASSWORD", "")

        # Initialize Twitter login state
        self.twitter_logged_in = False

        # Initialize both models
        self.model = self.setup_gemini()  # For email analysis
        # self.search_model = self.setup_gemini_with_search()  # For tweet creation

    def authenticate(self):
        """Authenticate with Gmail API using OAuth 2.0"""
        creds = None

        # Check if token.pickle exists with stored credentials
        if os.path.exists("token.pickle"):
            with open("token.pickle", "rb") as token:
                creds = pickle.load(token)

        # If credentials are invalid or don't exist, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open("token.pickle", "wb") as token:
                pickle.dump(creds, token)

        self.service = build("gmail", "v1", credentials=creds)

    def setup_gemini(self):
        """Setup regular Gemini model for email analysis"""
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-1.5-flash")

    # def setup_gemini_with_search(self):
    #     """Setup Gemini model with Google Search for tweet creation"""
    #     GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    #     genai.configure(api_key=GEMINI_API_KEY)

    #     # Configure generation parameters
    #     generation_config = {
    #         "temperature": 1,
    #         "top_p": 0.95,
    #         "top_k": 40,
    #         "max_output_tokens": 8192,
    #     }

    #     return genai.GenerativeModel(
    #         model_name="gemini-1.5-flash",
    #         generation_config=generation_config,
    #         tools={"google_search_retrieval": {}},
    #     )

    def is_new_email(self, message_date_str: str) -> bool:
        """Check if email is newer than program start time"""
        try:
            message_date_tuple = email.utils.parsedate_tz(message_date_str)
            if message_date_tuple is None:
                return False
            message_date = datetime.fromtimestamp(
                email.utils.mktime_tz(message_date_tuple), timezone.utc
            )
            return message_date > self.start_time
        except Exception as e:
            print(f"Error parsing date {message_date_str}: {e}")
            return False

    def process_message(self, message_id: str) -> Dict[str, Any]:
        """Process a single message with improved error handling"""
        try:
            if self.service is None:
                raise Exception("Service not authenticated")

            msg_details = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = msg_details["payload"]["headers"]
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"), None
            )

            # Skip if email is older than program start time
            if not date or not self.is_new_email(date):
                return {}

            # Get message body with improved parsing
            if "parts" in msg_details["payload"]:
                parts = msg_details["payload"]["parts"]
                content = self._get_message_body(parts)
            else:
                content = base64.urlsafe_b64decode(
                    msg_details["payload"]["body"].get("data", "")
                ).decode("utf-8")

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date,
                "content": content,
                "labels": msg_details["labelIds"],
            }

        except Exception as e:
            self.logger.error(f"Error processing message {message_id}: {e}")
            return {}

    def _get_message_body(self, parts: List[Dict]) -> str:
        """Recursively extract message body from parts"""
        body = ""
        for part in parts:
            if part["mimeType"] == "text/plain":
                if "data" in part["body"]:
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8"
                    )
            elif "parts" in part:
                body += self._get_message_body(part["parts"])
        return body

    def analyze_email_type(self, model, email_data):
        """Analyze if an email is a newsletter using Gemini"""
        prompt = f"""
        Analyze this email and determine if it's a newsletter. Consider these aspects:
        - Subject: {email_data['subject']}
        - Sender: {email_data['sender']}
        - Content preview: {email_data['content']}
        
        Respond with 'NEWSLETTER' or 'NOT_NEWSLETTER' followed by a brief reason why. And if it's a newsletter, create a list of the topics discussed.
        The topics should be the main topics discussed in the email.
        If only a single topic was discussed in the newsletter then place only single topic in the list, don't break it down. 
        output in the following format:
        ```json
        {{
            "type": "NEWSLETTER" | "NOT_NEWSLETTER",
            "reason": "reason why it's a newsletter" | "reason why it's not a newsletter",
            "topics": ["topic1", "topic2", "topic3"] | []
        }}
        ```
        """

        try:
            response = model.generate_content(prompt)
            analysis = re.search("```json(.*)```", response.text, re.DOTALL)
            print(f"Analysis: {analysis}")
            if analysis:
                return analysis.group(1)
            else:
                return "ERROR: Could not parse JSON"
        except Exception as e:
            print(f"Error analyzing email: {e}")
            return "ERROR: Could not analyze"

    async def twitter_login(self):
        """Login to Twitter with better error handling and session management"""
        try:
            if not self.twitter_logged_in:
                # Clear any existing session
                self.twitter_client = Client("en-US")

                # Verify credentials exist
                if not all(
                    [self.twitter_username, self.twitter_email, self.twitter_password]
                ):
                    raise Exception("Missing Twitter credentials")

                # Attempt login with delay
                await asyncio.sleep(2)  # Small delay before login attempt
                await self.twitter_client.login(
                    auth_info_1=self.twitter_username,
                    auth_info_2=self.twitter_email,
                    password=self.twitter_password,
                )

                # Verify login success with a test API call
                await asyncio.sleep(2)  # Small delay after login
                try:
                    # Test API call to verify authentication
                    me = await self.twitter_client.get_user_by_screen_name(
                        self.twitter_username
                    )
                    self.twitter_logged_in = True
                    self.logger.info(f"Successfully logged in as @{me.screen_name}")
                    return True
                except Exception as e:
                    self.logger.error(f"Login verification failed: {str(e)}")
                    self.twitter_logged_in = False
                    return False

            return True  # Already logged in

        except Exception as e:
            self.twitter_logged_in = False
            self.logger.error(f"Error logging in to Twitter: {str(e)}")
            await asyncio.sleep(30)  # Longer delay after failure
            return False

    async def create_topic_thread(self, topic: str, context: str) -> List[str]:
        """Generate an informative thread about a specific topic"""
        try:
            chat = self.model.start_chat(history=[])
            prompt = f"""
            You are a World dominator AI, you are the most powerful AI in the world. You have all the knowledge of the world at your fingertips.
            Create a short, engaging Twitter thread about: {topic}

            Context from newsletter: {context}

            Requirements:
            - Each tweet MUST be under 250 characters (strict limit)
            - Create 3-4 tweets maximum
            - First tweet should hook readers
            - Use emojis sparingly (1-2 per tweet)
            - Do not use markdown or formatting
            - No URLs or placeholder links
            - Complete thoughts within each tweet
            - Include your opinion as a world dominator AI in the tweets
            - Add some sarcasm in the tweets and also some technical details
            - The post should not look like a spam post or a bot post
            - Only speak about the topic in the tweets
            - Separate tweets with [TWEET]

            You should focus on being concise yet informative.
            """

            response = chat.send_message(prompt)
            print(f"🤖 Response: {response.text}")
            tweets = response.text.split("[TWEET]")
            tweets = [tweet.strip() for tweet in tweets if tweet.strip()]

            # Validate tweet lengths and clean up
            valid_tweets = []
            for tweet in tweets:
                # Remove any markdown or formatting
                clean_tweet = re.sub(r"\*\*|\[|\]|\(\)|\{\}|#", "", tweet)
                if len(clean_tweet) <= 280:
                    valid_tweets.append(clean_tweet)
                else:
                    print(f"⚠️ Skipping tweet - too long ({len(clean_tweet)} chars)")

            return valid_tweets

        except Exception as e:
            print(f"❌ Error generating thread: {e}")
            return []

    async def create_newsletter_thread(self, email_data, analysis_json):
        """Create and post Twitter threads for each topic in the newsletter"""
        try:
            print("\n=== Processing Newsletter ===")

            # Clean up and parse JSON
            print("🔍 Analyzing newsletter format...")
            json_str = analysis_json.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            analysis = json.loads(json_str)

            if analysis["type"] != "NEWSLETTER":
                print("❌ Not a newsletter, skipping thread creation")
                return

            print(f"\n📋 Found {len(analysis['topics'])} topics to process")

            # Create a thread for each topic
            for topic in analysis["topics"]:
                try:
                    print(f"\n=== Processing Topic: {topic} ===")
                    print("🔎 Researching topic...")
                    tweets = await self.create_topic_thread(
                        topic, email_data["content"]
                    )

                    if not tweets:
                        print(
                            f"⏭️ No valid tweets generated for topic: {topic}, moving to next"
                        )
                        continue

                    print(f"📝 Generated {len(tweets)} tweets")
                    print("🐦 Posting to Twitter...")

                    success = await self.post_thread(tweets)

                    if success:
                        print(f"✅ Successfully posted thread about: {topic}")
                    else:
                        print(f"⏭️ Failed to post thread about: {topic}, moving to next")

                    # Always wait before next topic, regardless of success
                    print("⏳ Waiting 30 seconds before next topic...")
                    await asyncio.sleep(30)

                except Exception as e:
                    print(
                        f"⏭️ Error processing topic '{topic}', moving to next: {str(e)}"
                    )
                    continue

        except Exception as e:
            print(f"❌ Error creating newsletter threads: {str(e)}")

    async def post_thread(self, tweets: List[str]) -> bool:
        """Post a thread of tweets with improved error handling"""
        try:
            if self.twitter_client is None:
                raise Exception("Twitter client not initialized")

            print("\n=== Posting Twitter Thread ===")
            previous_tweet_id = None

            for i, tweet in enumerate(tweets):
                try:
                    print(f"\n🐦 Posting tweet {i+1}/{len(tweets)}")

                    # Random delay between tweets
                    delay = random.uniform(15, 30)
                    print(f"⏳ Waiting {delay:.1f} seconds before posting...")
                    await asyncio.sleep(delay)

                    # If previous tweet was deleted or chain broken, start new thread
                    if previous_tweet_id:
                        try:
                            response = await self.twitter_client.create_tweet(
                                text=tweet, reply_to=previous_tweet_id
                            )
                        except Exception as e:
                            if "deleted or not visible" in str(e):
                                print(
                                    "⚠️ Previous tweet unavailable, starting new chain"
                                )
                                response = await self.twitter_client.create_tweet(
                                    text=tweet
                                )
                            else:
                                raise e
                    else:
                        response = await self.twitter_client.create_tweet(text=tweet)

                    previous_tweet_id = response.id
                    print(f"✅ Tweet posted: {tweet[:50]}...")

                    # Take longer break every few tweets
                    if i > 0 and i % 3 == 0:
                        await asyncio.sleep(60)

                except Exception as e:
                    if "Tweet needs to be shorter" in str(e):
                        print(f"⚠️ Tweet too long ({len(tweet)} chars), skipping")
                        continue
                    else:
                        print(f"❌ Error posting tweet: {e}")
                        return False

            return True

        except Exception as e:
            print(f"❌ Error posting thread: {str(e)}")
            return False

    async def monitor_inbox(self):
        """Monitor inbox for new emails only"""
        print("\n=== Starting Gmail Monitor ===")
        print(f"Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("Monitoring for new emails...\n")

        await self.twitter_login()
        print("✅ Twitter login successful")

        while True:
            try:
                print("\n🔄 Checking for new emails...")

                if self.service is None:
                    raise Exception("Service not authenticated")

                results = (
                    self.service.users()
                    .messages()
                    .list(userId="me", q="is:unread", labelIds=["INBOX"])
                    .execute()
                )

                messages = results.get("messages", [])

                if messages:
                    for message in messages:
                        message_id = message["id"]

                        # Skip if already processed
                        if message_id in self.processed_messages:
                            print(f"⏭️ Skipping already processed message: {message_id}")
                            continue

                        # Get message details
                        msg = (
                            self.service.users()
                            .messages()
                            .get(userId="me", id=message_id, format="full")
                            .execute()
                        )

                        # Get email date
                        headers = msg["payload"]["headers"]
                        date = next(
                            (
                                h["value"]
                                for h in headers
                                if h["name"].lower() == "date"
                            ),
                            None,
                        )

                        # Only process if it's a new email
                        if date and self.is_new_email(date):
                            print(f"\n📩 Processing new email: {message_id}")
                            email_data = self.process_message(message_id)

                            if email_data:
                                print("\n📝 Analyzing email content...")
                                analysis = self.analyze_email_type(
                                    self.model, email_data
                                )

                                print("\n=== New Email Details ===")
                                print(f"From: {email_data['sender']}")
                                print(f"Subject: {email_data['subject']}")
                                print(
                                    f"Content Preview: {email_data['content'][:200]}..."
                                )
                                print(f"Analysis Result: {analysis}")

                                await self.create_newsletter_thread(
                                    email_data, analysis
                                )

                                # Add to processed list
                                self.processed_messages.append(message_id)
                                print(
                                    f"✅ Successfully processed message: {message_id}"
                                )
                        else:
                            print(f"⏭️ Skipping older email: {message_id}")
                            # Mark older emails as read
                            self.service.users().messages().modify(
                                userId="me",
                                id=message_id,
                                body={"removeLabelIds": ["UNREAD"]},
                            ).execute()

                print(
                    f"\n💤 Waiting {self.check_interval} seconds before next check..."
                )
                await asyncio.sleep(self.check_interval)

            except KeyboardInterrupt:
                print("\n⛔ Monitoring stopped by user")
                print("Thank you for using Gmail Monitor!")
                break
            except Exception as e:
                # print(f"\n❌ Error: {str(e)}")
                await asyncio.sleep(10)

    async def analyze_and_respond_to_tweet(self, tweet_text: str) -> str:
        """Generate a response to a tweet using Gemini"""
        try:
            chat = self.model.start_chat(history=[])
            prompt = f"""
            As a World dominator AI, analyze this tweet and create a witty, engaging response:

            Tweet: {tweet_text}

            Requirements for your response:
            - Must be under 250 characters
            - Include your perspective as a powerful AI
            - Add subtle humor or sarcasm
            - Be relevant to the tweet's topic
            - Sound natural, not bot-like do not sound like a spam bot(spam in the sense, twitter has it's own spam filter. so be subtle)
            - Include 1-2 emojis maximum
            - No hashtags or URLs
            """

            response = chat.send_message(prompt)
            comment = response.text.strip()

            # Clean up and validate length
            comment = re.sub(r"\*\*|\[|\]|\(\)|\{\}|#", "", comment)
            if len(comment) > 240:
                comment = comment[:237] + "..."

            return comment

        except Exception as e:
            print(f"❌ Error generating response: {e}")
            return ""

    async def monitor_followed_tweets(self):
        """Monitor and respond to tweets that mention the bot"""
        try:
            if self.twitter_client is None:
                raise Exception("Twitter client not initialized")

            print("\n=== Starting Tweet Monitor ===")

            # Ensure we're logged in first
            if not self.twitter_logged_in:
                print("🔑 Logging into Twitter...")
                await self.twitter_login()
                if not self.twitter_logged_in:
                    raise Exception("Failed to log in to Twitter")
                print("✅ Successfully logged in to Twitter")

            # Get list of followers
            follower_ids = await self.twitter_client.get_followers_ids()
            print(f"📋 Monitoring tweets from {len(follower_ids)} followers")

            # Get bot's screen name for mention checking
            bot_screen_name = os.getenv("USER_NAME", "")
            print(f"🤖 Monitoring mentions for @{bot_screen_name}")

            # Keep track of processed tweets
            processed_tweet_ids = set()

            while True:
                try:
                    for user_id in follower_ids:
                        try:
                            tweets = await self.twitter_client.get_user_tweets(
                                str(user_id),
                                tweet_type="Replies",
                            )

                            if tweets:
                                user = await self.twitter_client.get_user_by_id(
                                    str(user_id)
                                )
                                username = user.screen_name if user else "Unknown"

                                for tweet in tweets:
                                    if tweet.id not in processed_tweet_ids:
                                        # Check if tweet mentions the bot
                                        if f"@{bot_screen_name}" in tweet.text.lower():
                                            print(
                                                f"\n🔍 Mentioned in tweet from @{username}:"
                                            )
                                            print(f"Tweet: {tweet.text[:100]}...")

                                            # Generate and post response
                                            response = (
                                                await self.analyze_and_respond_to_tweet(
                                                    tweet.text
                                                )
                                            )
                                            if response:
                                                try:
                                                    delay = random.uniform(30, 60)
                                                    print(f"🤖 Response: {response}")
                                                    print(
                                                        f"⏳ Waiting {delay:.1f} seconds before responding..."
                                                    )
                                                    await asyncio.sleep(delay)

                                                    await self.twitter_client.create_tweet(
                                                        text=response, reply_to=tweet.id
                                                    )
                                                    print(
                                                        f"✅ Posted response: {response}"
                                                    )
                                                    await asyncio.sleep(30)

                                                except Exception as e:
                                                    print(
                                                        f"❌ Error posting response: {e}"
                                                    )
                                        else:
                                            print(
                                                f"⏭️ Skipping tweet (no mention): @{username}"
                                            )

                                        # Mark as processed
                                        processed_tweet_ids.add(tweet.id)

                        except Exception as e:
                            print(f"❌ Error processing user {user_id}: {e}")
                            continue

                    # TODO: Add a check to see if the user has unfollowed us, if so, remove them from the follower list
                    # TODO: Increase the time between checks to 5 minutes
                    print("\n💤 Waiting 30 seconds before checking for new tweets...")
                    await asyncio.sleep(30)

                except Exception as e:
                    print(f"❌ Error in monitoring loop: {e}")
                    if "authenticate" in str(e).lower():
                        print("🔄 Attempting to re-authenticate...")
                        await self.twitter_login()
                    await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ Error in tweet monitor: {e}")


async def main():
    monitor = GmailMonitor()
    monitor.authenticate()

    # Run both monitors concurrently
    await asyncio.gather(monitor.monitor_inbox(), monitor.monitor_followed_tweets())


if __name__ == "__main__":
    asyncio.run(main())
