# How to publish the ARC dataset v1.1 (you do this; nothing has been uploaded)

v1.1 = v1.0 (Train Ticket, rows unchanged) + Online Boutique. Because nothing was ever published, v1.1 is the first public version.

MSR 2027 Data and Tool Showcase asks for the data to be available to reviewers at submission and confidential until publication.
So the plan is: upload to Zenodo with **restricted access**, give reviewers a private link, and make it open only after acceptance.

## 0. Before anything
1. Check `build-report.txt`: Train Ticket 1,795 + Boutique 280 usable campaign episodes (2,075); saturated 389 + 59.
2. Look at one released JSON (`meta.json` of any episode, in both Train Ticket and Boutique archives) to confirm there is no host name or personal path left.
3. Final author list and affiliations are in `CITATION.cff` and `zenodo.json`. Add ORCIDs if wanted.
4. Test first with a small dummy file (see step 1.2) to see exactly how restricted access and the share link behave in the current Zenodo
   interface; menu names change.

## 1. Zenodo (the archive and the DOI)
1. Make an account at https://zenodo.org (log in with GitHub or ORCID).
2. Try a dummy record with access set to "restricted" and create the access link to see how a reviewer would open it.
3. New upload -> upload the files in the `zenodo/` folder (the seven `arc-raw-*.tar.gz`, the tables, the documents, `SHA256SUMS.txt`)
   and `arc-testbed-code-v1.1.zip` (the code at the release tag). Our total is about 1.1 GB, far below the limit.
4. Click "Reserve DOI": you get the DOI before publishing. Put it in `CITATION.cff` (`doi:`) and in the paper.
5. Fill the form from `zenodo.json` (title, creators, description, licence CC-BY-4.0, keywords). Set access to **restricted** and create
   a link for reviewers; put that link in the HotCRP submission (not in the PDF if the track asks for confidentiality).
6. Re-read everything, then Publish. A published record cannot be deleted; files cannot be changed (new versions can be added).
7. After acceptance (camera-ready, 24 January 2027): change access to open, then add the DOI-based citation to the paper.
8. Optional: connect the GitHub repository to Zenodo (Settings -> GitHub) so a GitHub release also archives the code.

## 2. Hugging Face (browsing and `datasets` loading) - after acceptance
A private Hugging Face repo can only be seen by invited accounts, so do not use it for the review. Upload after acceptance:
1. Account at https://huggingface.co and an access token with "write" role (Settings -> Access Tokens). Never paste the token into a file or chat.
2. Create a dataset repo (New -> Dataset), name e.g. `arc-remediation-damage`, licence CC BY 4.0.
3. Upload the files in the `hf/` folder (tables, documents, loader; not the raw archives, those are on Zenodo):
   ```bash
   pip install -U huggingface_hub
   huggingface-cli login            # paste the token when asked
   huggingface-cli upload <your-username>/arc-remediation-damage ./hf . --repo-type dataset
   ```
4. Open the dataset page: the YAML block at the top of `README.md` makes the card; add the DOI link once you have it.

## 3. After publishing
Put the DOI and the Hugging Face link in the paper, `README.md` of the code repository and `CITATION.cff`; tag the code repository `v1.1`.
Never edit a published version; corrections go into a new version (v1.1.1).
