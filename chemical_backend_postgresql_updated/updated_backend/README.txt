UPDATED BACKEND FILES (Supabase PostgreSQL)

1. Back up your current backend/api.py, backend/admin_routes.py, backend/database.py.
2. Replace them with the three .py files in this folder.
3. Ensure backend/requirements.txt contains:
   Flask
   flask-cors
   python-dotenv
   itsdangerous
   Werkzeug
   psycopg[binary]
4. Set DATABASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD_HASH and ADMIN_SECRET_KEY in your backend deployment environment. Never commit .env.
5. Run SQL below ONCE in Supabase SQL Editor after importing CSV with explicit IDs, to synchronize the ID sequence:
   SELECT setval(pg_get_serial_sequence('public.chemicals', 'id'), COALESCE((SELECT MAX(id) FROM public.chemicals), 1), true);
6. Deploy only after verifying environment variables and your Vercel entrypoint/rewrites.

NOTE: Python syntax compilation passed; actual Supabase database and Vercel deployment were not tested here.
