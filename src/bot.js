import dotenv from 'dotenv';
import { Telegraf, Markup } from 'telegraf';
import { supabase, ensureUser } from './supabaseClient.js';

dotenv.config();

if (!process.env.BOT_TOKEN) {
  console.error('BOT_TOKEN is required. Add it to .env or Railway Variables.');
  process.exit(1);
}

const bot = new Telegraf(process.env.BOT_TOKEN);

const DEFAULT_CATEGORIES = {
  expense: [
    'Продукты',
    'Кафе и рестораны',
    'Транспорт',
    'Авто',
    'Жильё',
    'Связь и интернет',
    'Здоровье',
    'Одежда',
    'Развлечения',
    'Образование',
    'Другое',
  ],
  income: ['Зарплата', 'Подработка', 'Бизнес', 'Подарок', 'Другое'],
};

function normalizeWord(value = '') {
  return value.toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9\s]/gi, '');
}

function parseAmount(input) {
  const s = String(input || '').trim();
  if (!s) return null;
  const cleaned = s
    .replace(/\s+/g, '')
    .replace(',', '.')
    .replace(/(\d+)к/gi, '$1000')
    .replace(/(\d+)k/gi, '$1000');
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

function guessKind(text) {
  const hay = normalizeWord(text);
  const incomeHints = ['зарплата', 'получил', 'доход', 'прибыль', 'перевод', 'заработал', 'премия'];
  return incomeHints.some((n) => hay.includes(n)) ? 'income' : 'expense';
}

function buildStatsText(rows, label) {
  const total = rows.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  return `${label}: ${total.toFixed(2)} ₽\n` + rows.map((row) => `• ${row.category}: ${Number(row.amount).toFixed(2)} ₽`).join('\n');
}

bot.start(async (ctx) => {
  await ensureUser(ctx.from);
  const text = [
    'Привет! Я помогу вести финансы.',
    '',
    'Примеры:',
    '• вода 50',
    '• такси 350',
    '• зарплата 80000',
    '• /today',
    '• /month',
    '• /budget Продукты 20000',
  ].join('\n');
  await ctx.reply(text, Markup.keyboard([
    ['Сегодня', 'Неделя'],
    ['Месяц', 'Последние'],
    ['Бюджеты', 'Статистика'],
  ]).resize());
});

bot.command('today', async (ctx) => {
  if (!supabase) return ctx.reply('Supabase не подключён. Настройте переменные окружения.');

  const { data, error } = await supabase
    .from('transactions')
    .select('*')
    .eq('user_id', ctx.from.id)
    .gte('created_at', new Date(new Date().setHours(0, 0, 0, 0)).toISOString())
    .order('created_at', { ascending: false });

  if (error) return ctx.reply(`Ошибка: ${error.message}`);
  await ctx.reply(buildStatsText(data || [], 'Сегодня'));
});

bot.hears(/^(Сегодня|today)$/i, async (ctx) => ctx.telegram.sendMessage(ctx.chat.id, 'Используйте /today'));

bot.on('text', async (ctx) => {
  const text = ctx.message.text || '';
  if (text.startsWith('/')) return;

  const amount = parseAmount(text);
  if (!amount) return;

  const kind = guessKind(text);
  const category = kind === 'expense' ? 'Другое' : 'Зарплата';

  if (!supabase) {
    return ctx.reply(`Запись принята локально: ${kind} ${amount} ₽ / ${category}`);
  }

  const { error } = await supabase.from('transactions').insert({
    user_id: ctx.from.id,
    kind,
    amount,
    category,
    note: text.slice(0, 80),
    created_at: new Date().toISOString(),
  });

  if (error) {
    return ctx.reply(`Ошибка сохранения: ${error.message}`);
  }

  await ctx.reply(`Добавлено: ${kind === 'expense' ? 'расход' : 'доход'} • ${amount} ₽ • ${category}`);
});

bot.launch();
console.log('Finance tracker bot started');

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
