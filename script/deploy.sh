source $(dirname "$0")/values.sh

gcloud run deploy $SERVICE_NAME \
    --source="." \
    --platform=managed \
    --region=$LOCATION \
    --cpu=1 \
    --memory=1Gi \
    --min-instances=1 \
    --max-instances=10 \
    --service-account=$SERVICE_ACCOUNT \
    --allow-unauthenticated \
    --project=$PROJECT_ID  \
    --timeout=$TIMEOUT \
    --concurrency=$CONCURRENCY \
    --set-env-vars=PUBLIC_SERVER_HOSTNAME="$PUBLIC_SERVER_HOSTNAME",TWILIO_ACCOUNT_SID="$TWILIO_ACCOUNT_SID",AUTH_TOKEN_SECRET_PATH="$AUTH_TOKEN_SECRET_PATH",NUMBERS_COLLECTION_ID="$NUMBERS_COLLECTION_ID" \
    --set-secrets=TWILIO_AUTH_TOKEN="$TWILIO_AUTH_TOKEN_PATH" \
    --allow-unauthenticated
