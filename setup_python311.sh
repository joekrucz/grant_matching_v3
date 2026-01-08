#!/bin/bash
# Setup script for Python 3.11 environment

set -e

echo "Setting up Python 3.11 for Grants Aggregator V2..."
echo ""

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "This script is optimized for macOS. For other systems, please install Python 3.11 manually."
    exit 1
fi

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "Homebrew is not installed. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Install pyenv if not installed
if ! command -v pyenv &> /dev/null; then
    echo "Installing pyenv..."
    brew install pyenv
    
    # Add pyenv to shell
    if [[ "$SHELL" == *"zsh"* ]]; then
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
        echo 'eval "$(pyenv init -)"' >> ~/.zshrc
        echo "Added pyenv to ~/.zshrc. Please run: source ~/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bash_profile
        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bash_profile
        echo 'eval "$(pyenv init -)"' >> ~/.bash_profile
        echo "Added pyenv to ~/.bash_profile. Please run: source ~/.bash_profile"
    fi
    
    # Load pyenv for current session
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"
fi

# Install Python 3.11.9
echo "Installing Python 3.11.9 (this may take a few minutes)..."
pyenv install 3.11.9

# Set local Python version
echo "Setting Python 3.11.9 for this project..."
cd "$(dirname "$0")"
pyenv local 3.11.9

# Verify installation
echo ""
echo "Verifying Python version..."
python --version

# Create/update virtual environment
if [ -d "venv" ]; then
    echo ""
    echo "Removing old virtual environment..."
    rm -rf venv
fi

echo "Creating new virtual environment with Python 3.11..."
python -m venv venv

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Activate the virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. Install dependencies:"
echo "   pip install --upgrade pip"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Run tests:"
echo "   pytest"




