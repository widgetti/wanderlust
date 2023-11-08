FROM python:3.11

# Set up a new user named "user" with user ID 1000 for permission
RUN useradd -m -u 1000 user
# Switch to the "user" user
USER user
# Set home to the user's home directory
ENV HOME=/home/user \
	PATH=/home/user/.local/bin:$PATH

# Upgreade pip
RUN pip install --no-cache-dir --upgrade pip

COPY --chown=user requirements.txt .

# Install requirements
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user wanderlust.py wanderlust.py

ENTRYPOINT ["solara", "run", "wanderlust.py", "--host=0.0.0.0", "--port", "7860"]
