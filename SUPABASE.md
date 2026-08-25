# Ce qu'il reste à faire dans Supabase

Deux choses, et elles ne peuvent pas être faites depuis le code : elles vivent
dans le tableau de bord de ton projet.

## 1. Fermer la base en lecture (URGENT)

La clé `anon` est dans le code source. C'est **normal** : elle est publique par
conception. Ce qui la rend inoffensive, c'est la *Row Level Security*. Sans
elle, n'importe qui muni de cette clé lit les analyses de tout le monde.

Dans **SQL Editor**, colle ceci :

```sql
-- Personne ne lit ni n'écrit sans policy explicite.
alter table public.skyn_reports enable row level security;

-- Chacun ne voit que ses propres analyses.
create policy "lecture de ses propres rapports"
  on public.skyn_reports for select
  using (auth.uid()::text = user_id);

create policy "ecriture de ses propres rapports"
  on public.skyn_reports for insert
  with check (auth.uid()::text = user_id);

create policy "suppression de ses propres rapports"
  on public.skyn_reports for delete
  using (auth.uid()::text = user_id);
```

**Vérifie ensuite** que ça marche, depuis n'importe quel terminal :

```bash
curl "https://axpyatbjvvoxjtwkrhwu.supabase.co/rest/v1/skyn_reports?select=id&limit=1" \
  -H "apikey: <ta clé anon>"
```

La réponse doit être `[]`. Si elle contient des lignes, la RLS n'est pas active
et il ne faut pas publier.

## 2. La suppression de compte

L'app appelle une fonction `delete_account()`. Tant qu'elle n'existe pas, elle
supprime seulement les *données* et le dit honnêtement à l'utilisateur, sans
prétendre avoir fermé le compte. Apple exige la fermeture complète.

Toujours dans **SQL Editor** :

```sql
create or replace function public.delete_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.skyn_reports where user_id = auth.uid()::text;
  delete from auth.users where id = auth.uid();
end;
$$;

revoke all on function public.delete_account() from public, anon;
grant execute on function public.delete_account() to authenticated;
```

**Vérifie** : crée un compte de test, lance « Supprimer mon compte » dans les
réglages, et confirme dans *Authentication → Users* qu'il a disparu. Le message
affiché par l'app doit dire « Compte supprimé ». S'il dit autre chose, la
fonction n'est pas en place.
