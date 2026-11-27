# Bot rotation hebdomadaire : SIMULATION uniquement

Chaque semaine, le bot place 1000 € **fictifs** sur l'actif le plus fort sur 12 mois (Bitcoin, Ether ou actions mondiales), ou en liquide si tout baisse.
Il suit en même temps le mélange fixe (1/3 chacun, rééquilibré 1 fois par an) et BTC seul.

- Aucun argent réel, aucune clé de plateforme, aucun ordre passé.
- Il tourne gratuitement sur GitHub, 2 fois par jour : ton PC peut rester éteint.
- S'il rate un lancement (panne, coupure), il rattrape tout seul au suivant.
- Tu reçois un message Telegram à chaque décision (en général le mardi matin), et une alerte si une donnée manque.
- Le tableau de bord est en ligne : `https://TON-PSEUDO.github.io/rotation-bot/`

---

## Installation (environ 15 minutes, sans coder)

### 1. Créer ton bot Telegram (sur ton téléphone ou ton PC)
1. Ouvre Telegram et cherche **@BotFather** (badge bleu certifié). Ouvre-le et appuie sur **Démarrer**.
2. Envoie `/newbot`.
3. Il demande un **nom** : tape par exemple `Rotation Simulation`.
4. Il demande un **identifiant** finissant par `bot` : par exemple `rotation_stoqh_bot` (s'il est pris, ajoute des chiffres).
5. Il répond avec une **clé** qui ressemble à `1234567890:AAH...`. C'est ta **clé** : ne la montre à personne, ne la colle dans aucun fichier ni dans une conversation.
6. Clique sur le lien `t.me/...` de ton bot dans ce message et appuie sur **Démarrer**. Sans ça, le bot n'a pas le droit de t'écrire.

### 1 bis. Récupérer ton identifiant (sans bot tiers)
1. Dans Telegram, ouvre **ton** bot (celui créé à l'étape 1), appuie sur **Démarrer** et envoie-lui `salut`.
2. Sur ton PC, ouvre ton navigateur et tape dans la barre d'adresse (remplace `CLÉ` par ta clé, sans espace) :
   `https://api.telegram.org/botCLÉ/getUpdates`
3. La page affiche du texte. Cherche `"chat":{"id":` : le nombre juste après (par exemple `987654321`) est ton **identifiant**.
4. Si la page affiche seulement `"result":[]`, renvoie `salut` à ton bot puis recharge la page.
5. Ferme l'onglet ensuite (l'adresse contient ta clé).

N'utilise pas de bot « userinfo » trouvé dans la recherche : beaucoup sont des imitations.

### 2. Créer le dépôt GitHub
1. Va sur github.com, connecte-toi.
2. En haut à droite : **+** → **New repository**.
3. Nom : `rotation-bot`. Coche **Public** (obligatoire pour le tableau de bord gratuit). Ne coche rien d'autre. **Create repository**.

### 3. Envoyer les fichiers
1. Dézippe `rotation-bot.zip` sur ton PC.
2. Sur la page du dépôt : clique sur **uploading an existing file**.
3. Ouvre le dossier dézippé, sélectionne **tout son contenu** (les dossiers `.github`, `bot`, `docs`, `state`, `tests` et les fichiers) et glisse-le dans la page.
4. En bas : **Commit changes**.
5. Vérifie que le dossier `.github` apparaît bien dans la liste. S'il manque, recommence en glissant le dossier `.github` seul.

### 4. Ranger la clé et l'identifiant dans les secrets GitHub
Les secrets sont chiffrés par GitHub : personne ne peut les relire, même sur un dépôt public, et ils n'apparaissent jamais dans le code ni dans les journaux.
1. Dans le dépôt : **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Name : `TELEGRAM_TOKEN` ; Secret : colle ta clé de BotFather → **Add secret**.
3. Encore **New repository secret** : Name : `TELEGRAM_CHAT_ID` ; Secret : ton identifiant (le nombre) → **Add secret**.
4. Vérifie l'orthographe exacte des deux noms (majuscules, tiret bas).

### 5. Autoriser le bot à enregistrer ses résultats
**Settings** → **Actions** → **General** → en bas, **Workflow permissions** : choisis **Read and write permissions** → **Save**.

### 6. Activer le tableau de bord
**Settings** → **Pages** → Source : **Deploy from a branch** → Branch : **main**, dossier **/docs** → **Save**.

### 7. Premier essai
1. Onglet **Actions** (accepte d'activer les workflows si GitHub le demande).
2. Clique sur **Bot rotation (simulation)** → **Run workflow** → coche **Envoyer seulement une notification de test** → **Run workflow**.
3. Après environ 1 minute, ton bot t'écrit sur Telegram « Rotation : test ». ✅
   Si la ligne devient rouge : clique dessus, puis sur l'étape **Notification de test**. Le message explique quoi corriger (clé fausse, /start oublié…).
4. Relance **Run workflow** sans cocher la case : le tableau de bord se remplit (au début il indique « Pas encore démarré »).

C'est fini. Ensuite, tout est automatique.

---

## Si quelque chose ne va pas
- **Croix rouge dans l'onglet Actions** : GitHub t'envoie un e-mail. Clique sur la ligne rouge pour voir l'erreur et envoie-moi une capture.
- **Message « donnée manquante »** : une source de prix ne répond pas ou est en retard. Le bot ne décide rien et réessaie seul au lancement suivant.
- **Clé volée ou montrée par erreur** : dans @BotFather, envoie `/revoke`, choisis ton bot, puis remplace le secret `TELEGRAM_TOKEN` par la nouvelle clé.
- **Plus aucun message pendant 2 semaines** : onglet Actions → vérifie que le workflow n'est pas désactivé (bouton **Enable workflow**).

## Détails
- Prix : actions = indice Nasdaq Developed Markets avec dividendes (FRED) ; crypto = Coinbase (Kraken en secours). Tout est en dollars.
- Décision : dernier jour de bourse de la semaine (clôture), exécution simulée à la clôture du jour de bourse suivant.
- Frais simulés : crypto 0,50 % par ordre (Kraken + glissement), actions 0,25 % (courtier + glissement). Impôts non simulés.
- Date de début : `config.json` (27/11/2026). Point prévu dans 6 mois avant toute décision d'argent réel.
- Tests automatiques : le bot ne tourne pas si un test échoue (`tests/test_bot.py`).
