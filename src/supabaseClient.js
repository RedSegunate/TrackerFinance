import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_ANON_KEY;

if (!supabaseUrl || !serviceRoleKey) {
  console.warn('Supabase env vars are missing. Bot will start in limited mode.');
}

export const supabase = supabaseUrl && serviceRoleKey
  ? createClient(supabaseUrl, serviceRoleKey, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
      },
    })
  : null;

export async function ensureUser(user) {
  if (!supabase) return null;

  const telegramId = String(user.id);
  const { data: existing, error: selectError } = await supabase
    .from('users')
    .select('*')
    .eq('telegram_id', telegramId)
    .maybeSingle();

  if (selectError) {
    throw selectError;
  }

  if (!existing) {
    const { error: insertError } = await supabase.from('users').insert({
      telegram_id: telegramId,
      username: user.username ?? null,
      first_name: user.first_name ?? null,
      last_name: user.last_name ?? null,
      created_at: new Date().toISOString(),
    });

    if (insertError) {
      throw insertError;
    }
  }

  return true;
}
