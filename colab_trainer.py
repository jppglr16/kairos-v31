# This runs on Google Colab
# Trains all V31 models
# Saves to Google Drive

from google.colab import drive
drive.mount('/content/drive')

# Copy training data
import shutil
shutil.copytree('/content/drive/MyDrive/kairos_data',
               '/content/kairos')

# Train all models
import subprocess
subprocess.run(['python3','v31_trainer.py'])
subprocess.run(['python3','v31_ensemble.py'])

# Save back to Drive
shutil.copytree('/content/kairos/ml_models',
               '/content/drive/MyDrive/kairos_models')
print('Training complete! Models saved!')
