import os
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string


def send_verification_email(user_email: str, verification_url: str, user_name: str = None) -> bool:
    """
    Send email verification link to user.
    
    Args:
        user_email: User's email address
        verification_url: Full URL with token for verification
        user_name: User's name (optional, for personalization)
    
    Returns:
        bool: True if email was sent successfully
    """
    if user_name is None:
        user_name = user_email.split('@')[0]
    
    subject = 'Verify your PixelMart account'
    
    # Plain text message
    message = f"""Hello {user_name},

Welcome to PixelMart! Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create an account with PixelMart, please ignore this email.

Best regards,
The PixelMart Team
"""
    
    # HTML message (optional enhancement)
    html_message = render_to_string('emails/verification.html', {
        'user_name': user_name,
        'verification_url': verification_url,
    })
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        # In development, log the email instead of failing
        if settings.DEBUG:
            print(f"[EMAIL MOCK] Verification URL: {verification_url}")
            return True
        return False


def send_welcome_email(user_email: str, user_name: str = None) -> bool:
    """
    Send welcome email after successful verification.
    """
    if user_name is None:
        user_name = user_email.split('@')[0]
    
    subject = 'Welcome to PixelMart!'
    
    message = f"""Hello {user_name},

Your email has been verified successfully!

You can now:
- Browse products from thousands of stores
- Create your own store and start selling
- Leave reviews and ratings
- And much more!

Get started: {settings.FRONTEND_URL or 'https://pixelmart.com'}

Best regards,
The PixelMart Team
"""
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        if settings.DEBUG:
            print(f"[EMAIL MOCK] Welcome email to: {user_email}")
            return True
        return False
