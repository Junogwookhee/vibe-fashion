-- Add the profile's default shipping address field for the My Page form.
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS address TEXT;
