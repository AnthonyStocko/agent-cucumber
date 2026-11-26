## Mémoire de travail du lot (obligatoire)

Ton contexte est limité et chaque tour relit tout ce qu'il contient. Ta mémoire durable est un seul fichier :
`${fichier}`. Son contenu actuel est recopié à la fin de ce bloc : c'est ton point de départ. Ne relis pas ce
fichier avec Read, sauf pour le modifier.

### Règles de lecture
- Commence par lire le contenu du fichier ci-dessous. Ne refais pas ce qui y figure comme établi ou écarté.
- Ne relis pas un fichier, une table ou une trace que la mémoire résume déjà. Exception : tu dois l'éditer, ou
  le résumé ne suffit pas pour décider.
- La mémoire ne passe jamais avant les leçons, le profil client, l'état réel des fichiers ou de la base.
  En cas de contradiction, vérifie, puis corrige la mémoire.

### Quand écrire (avec Edit, ou Write si le fichier est vide)
Écris dès que l'un de ces cas se produit :
1. Un fait est établi, avec sa preuve : valeur lue en base, message d'échec, sortie d'un step, ligne de code.
2. Une valeur de test est choisie : réserve, produit, quantité. Note aussi pourquoi.
3. Une piste est écartée.
4. Le contexte devient important. Repères :
   - un résultat d'outil de plus de 5 000 caractères ;
   - 8 appels d'outils depuis la dernière écriture ;
   - le tour ${tour_alerte}.
   À ce moment, condense ce que tu sais dans le fichier. Ensuite, travaille à partir de la mémoire, pas des
   résultats bruts.
5. Toujours avant ta réponse finale : écris l'état final et la prochaine étape.

### Format imposé (au plus ${max_lignes} lignes, réécrit, jamais allongé sans fin)
```
# Lot ${lot} — mémoire de travail
## Objectif
## Faits établis (fait — preuve courte)
## Valeurs retenues (valeur — raison)
## Pistes écartées (ne pas refaire — pourquoi)
## Hypothèses ouvertes (NON PROUVÉE — comment vérifier)
## Prochaine étape
```
- Une ligne par élément, 200 caractères au plus.
- Remplace un élément périmé, ne l'empile pas.
- Supprime ce qui ne sert plus à décider.
- Si le fichier dépasse la limite, compacte-le avant d'ajouter quoi que ce soit.

### Ne jamais écrire dans la mémoire
- les résultats d'outils bruts, ni le code ou les features en entier : donne seulement le chemin et la ligne ;
- les mots de passe, jetons, URL avec identifiants, ni les données personnelles du client.

### Contenu actuel de `${fichier}`
${contenu}
