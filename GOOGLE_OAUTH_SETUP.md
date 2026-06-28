# Google OAuth Setup Guide

To enable Google login functionality for your Meter Scanner application, follow these steps:

## 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the "Google+ API" and "OpenID Connect" APIs

## 2. Create OAuth 2.0 Credentials

1. In the Google Cloud Console, go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth 2.0 Client ID**
3. Select **Web application** as the application type
4. Add the following **Authorized redirect URIs**:
   - `http://localhost:5000/google/callback` (for development)
   - `https://yourdomain.com/google/callback` (for production)
5. Click **Create**

## 3. Get Your Credentials

After creating the OAuth 2.0 Client ID, you'll get:
- **Client ID** (e.g., `123456789-abc123def456.apps.googleusercontent.com`)
- **Client Secret** (e.g., `GOCSPX-abc123def456`)

## 4. Set Environment Variables

Set the following environment variables before running the application:

### Windows (Command Prompt):
```cmd
set GOOGLE_CLIENT_ID=your-client-id-here
set GOOGLE_CLIENT_SECRET=your-client-secret-here
```

### Windows (PowerShell):
```powershell
$env:GOOGLE_CLIENT_ID="your-client-id-here"
$env:GOOGLE_CLIENT_SECRET="your-client-secret-here"
```

### Linux/Mac:
```bash
export GOOGLE_CLIENT_ID="your-client-id-here"
export GOOGLE_CLIENT_SECRET="your-client-secret-here"
```

## 5. Run the Application

```bash
python app.py
```

## 6. Test Google Login

1. Navigate to `http://localhost:5000/login`
2. Click "Continue with Google"
3. Complete the Google authentication flow
4. You should be redirected back to your application dashboard

## Security Notes

- Never commit your client secrets to version control
- Use different credentials for development and production
- Regularly rotate your client secrets
- Monitor your OAuth usage in the Google Cloud Console

## Troubleshooting

### Common Issues:

1. **"redirect_uri_mismatch" error**
   - Make sure the redirect URI in Google Console matches exactly what's in your app
   - Check for trailing slashes and HTTP vs HTTPS

2. **"invalid_client" error**
   - Verify your Client ID and Client Secret are correct
   - Ensure environment variables are set properly

3. **"access_denied" error**
   - User denied access - this is normal behavior
   - User needs to grant permission for the app to access their profile

4. **"Google login is currently unavailable" error**
   - Check internet connection
   - Verify Google OAuth endpoints are accessible
   - Check application logs for detailed error messages

## Features Implemented

✅ **Google OAuth Login**
- Users can sign in with their Google account
- Automatic account creation for new users
- Account linking for existing users

✅ **User Profile Integration**
- Automatically imports user's name and email from Google
- Splits name into first and last name fields
- Creates unique username based on email

✅ **Security Features**
- Email verification check
- Secure token exchange
- Error handling and user feedback

✅ **Database Integration**
- Google ID stored in users table
- Backward compatibility with existing users
- Automatic schema updates

## Next Steps

After setting up Google OAuth, you can:
1. Add more social login providers (Facebook, GitHub, etc.)
2. Implement role-based access control
3. Add two-factor authentication
4. Create user profile management features

For more information, visit the [Google OAuth 2.0 documentation](https://developers.google.com/identity/protocols/oauth2).
