# Final Medallion Demo Preparation

This procedure reserves a clean, existing controlled source for the Senior
Director walkthrough without deleting relations or weakening overwrite
authority.

## Reserved presentation relations

- Source: `source.src_orders`
- Silver target created by the flow: `silver.src_orders`
- Gold target entered in the UI: `director_src_orders_20260726`

Do not rehearse with these reserved names after completing the preflight.

## Preflight

1. Start PostgreSQL, then start the API and frontend from the final candidate
   commit.
2. Do not run the backend test suite after this preflight. Its controlled
   source-ingest fixtures intentionally prepare test relations.
3. In Dataset Explorer, confirm `source.src_orders` is live and previews 10
   rows with the `id` column.
4. In Dataset Explorer, confirm `silver.src_orders` is absent.
5. Confirm `gold.director_src_orders_20260726` is absent.
6. If either target is present, stop. Do not drop or overwrite it as an
   improvised cleanup; reserve another source whose same-name Silver target is
   absent and choose a new Gold target name before the audience arrives.

## Browser walkthrough

1. Connect using manually entered demo credentials.
2. Discover and preview `source.src_orders`.
3. Continue through selection and metadata to Bronze.
4. Ingest `src_orders`, verify the live Bronze count and preview, then continue
   to Silver.
5. Add `id is not null`, save, generate, review, and execute.
6. Confirm Silver attribution, row count, and preview before continuing.
7. Select `src_orders` as the Silver source and enter
   `director_src_orders_20260726` as the Gold target.
8. Generate and load review, approve the exact revision, execute the candidate,
   and promote it.
9. Confirm live Gold discovery, metadata, count, and row preview.

No terminal command or database cleanup is required during the walkthrough.
