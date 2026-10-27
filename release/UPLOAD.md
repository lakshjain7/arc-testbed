# How to publish the ARC dataset v1.0 (you do this; nothing has been uploaded)

Do not publish before the guide has agreed (and before the paper cites it if you want the DOI in the paper: Zenodo gives the DOI
when you press Publish, so reserve it first, see step 2).

## 0. Before anything
1. Check `build-report.txt`: 1,795 campaign episodes, 28,769 scored rows, 389 saturated episodes.
2. Look at one released JSON (`meta.json` of any episode) to confirm there is no host name or personal path left.
3. Put the final author list, affiliations and (if wanted) ORCIDs in `CITATION.cff` and `zenodo.json`.

## 1. Zenodo (the archive and the DOI)
1. Make an account at https://zenodo.org (you can log in with GitHub or ORCID).
2. New upload -> upload the files in the `zenodo/` folder (the six `arc-raw-*.tar.gz`, the tables, the documents, `SHA256SUMS.txt`) and
   `arc-testbed-code-v1.0.zip` (the code at the release tag). Files up to 50 GB per record are accepted; ours total about 1 GB.
3. Click "Reserve DOI": you get the DOI before publishing, put it in `CITATION.cff` (`doi:`) and in the paper.
4. Fill the form from `zenodo.json` (title, creators, description, licence CC-BY-4.0, keywords).
5. Re-read everything, then Publish. A published record cannot be deleted; files cannot be changed (new versions can be added).
6. Optional: connect the GitHub repository to Zenodo (Settings -> GitHub) so a GitHub release also archives the code.

## 2. Hugging Face (browsing and `datasets` loading)
1. Make an account at https://huggingface.co and an access token with "write" role (Settings -> Access Tokens). Never paste the token into a file or chat.
2. Create a dataset repo (New -> Dataset), name e.g. `arc-remediation-damage`, licence CC BY 4.0, public.
3. Upload the files in the `hf/` folder (tables, documents, loader; not the raw archives, those are on Zenodo):
   ```bash
   pip install -U huggingface_hub
   huggingface-cli login            # paste the token when asked
   huggingface-cli upload <your-username>/arc-remediation-damage ./hf . --repo-type dataset
   ```
4. Open the dataset page: the YAML block at the top of `README.md` makes the card; add the DOI link once you have it.

## 3. After publishing
Put the DOI and the Hugging Face link in the paper, `README.md` of the code repository and `CITATION.cff`; tag the code repository `v1.0`.
Never edit a published version; corrections go into a new version (v1.0.1).
