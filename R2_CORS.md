# R2 CORS Configuration

For the **presigned upload system**, Flutter clients (especially Flutter Web) upload large cutting files (up to 40 MB - 50 MB) directly to Cloudflare R2 using HTTP `PUT`.

To allow browser uploads and downloads, Cloudflare R2 needs CORS configured.

### Applying CORS to R2

In the Cloudflare dashboard:
1. Go to **R2** -> Select your bucket (`cnc`) -> **Settings** -> **CORS Policy**.
2. Add / Edit CORS policy and paste:

```json
[
  {
    "AllowedOrigins": [
      "https://cncgroupjony.web.app",
      "http://localhost:55915",
      "http://localhost:*"
    ],
    "AllowedMethods": [
      "GET",
      "PUT",
      "HEAD"
    ],
    "AllowedHeaders": [
      "*"
    ],
    "ExposeHeaders": [
      "ETag"
    ],
    "MaxAgeSeconds": 3600
  }
]
```

Or using Wrangler CLI:
```bash
wrangler r2 bucket cors set <bucket-name> --file r2-cors.json
```
