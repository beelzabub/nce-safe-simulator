

export PATH="$PATH:/opt/homebrew/bin:/usr/bin"
export TOKEN='glpat-OtPmDQ0y17wwicsmMQaJZ2M6MQpvOjEKdTptaGFueQ8.01.171mp6qxv'
export TOKEN2='glpat-66StXqE3zaucPls1jeA8rGM6MQpvOjEKdTptaGFueQ8.01.170102ery'


# These make aws cli work
# 2. Append Zscaler cert to Python's trusted bundle
# cat ~/Desktop/ZscalerRootCA.pem >> $(python3 -m certifi)
export REQUESTS_CA_BUNDLE=$(python3 -m certifi)
export AWS_CA_BUNDLE=$(python3 -m certifi)


# Aliases
alias ls='ls -a'
alias ll='ls -al'
alias cl='clear'
alias dn='cd ..;cl;ls'
alias asdf='cd;cl'
alias editrc='vi ~/.zshrc'
alias soch='source ~/.zshrc'
alias de=deactivate
alias act='source bin/activate'


# Functions
hello() {
  echo "Hello Jamie!"
}

govenv() {

  local reqs_file=~/requirements.txt

  if [[ -z $1 ]]; then
    venv_dir=.venv
  else
    venv_dir=$1
  fi

  if [ -d $venv_dir ]; then
    echo "Sourcing your virtual environment in $venv_dir ..."
    source $venv_dir/bin/activate   
  else
    echo "Creating and sourcing a new virtual environment ..."
    python3 -m venv $venv_dir
    source $venv_dir/bin/activate 
    cd $venv_dir
  fi

  if [ -f $reqs_file ]; then
    echo "Installing requirements ..."
    pip install -r $reqs_file
  else
    echo "No requirements file; $reqs_file"
  fi



}

