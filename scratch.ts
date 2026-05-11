import { GoogleAuth } from 'google-auth-library';
import * as dotenv from "dotenv";

dotenv.config();

async function run() {
  const auth = new GoogleAuth({
    scopes: 'https://www.googleapis.com/auth/cloud-platform'
  });
  const client = await auth.getClient();
  const projectId = process.env.PROJECT_ID;
  const location = 'us-central1';

  const url = `https://${location}-aiplatform.googleapis.com/v1/projects/${projectId}/locations/${location}/publishers/google/models/text-embedding-004:predict`;
  
  const res = await client.request({
    url,
    method: 'POST',
    data: {
      instances: [
        { content: "thịt bò" }
      ]
    }
  });

  const embeddingValues = (res.data as any).predictions[0].embeddings.values;
  console.log('Dimension:', embeddingValues.length);
}

run().catch(console.error);
