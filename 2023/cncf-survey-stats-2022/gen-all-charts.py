import csv
import plotly.graph_objects as go
import numpy as np

# Get results from the CSV file
results = []
# curl https://raw.githubusercontent.com/cncf/surveys/main/cloudnative/2022%20CNCF%20Survey%20-%20Raw%20Data.csv -o raw.csv
with open('raw.csv', 'r', encoding='utf8', errors='ignore') as csv_file:
  csv_data = csv.reader(csv_file)

  for row in csv_data:
    # Put the data into the results variable if this line is not empty
    if len(row) > 0:
      results.append(row)

# Get a column number with answers for this question
def get_question_col(question):
  success = 0
  col_num = 0

  # Iterate through all columns until the needed title is found
  for col in results[0]:
    if col == question:
      success = 1
      print(question, 'corresponds to the', col_num, 'column')
      break
    col_num += 1

  if success:
    return col_num
  return -1

# Draw a chart based on the provided answers' data
def draw_chart_for_answers(question, answers, values, variants, total_answers):
  if variants:
    # Reverse everything to have it nicely sorted on the chart
    answers.reverse()
    values.reverse()

    # Draw a colored hortizontal bar chart
    fig = go.Figure(layout_title_text='CNCF Annual Survey 2022 data: ' + question + ' projects')

    i = 1
    while i < len(variants):
      v = []
      a = 0
      while a < len(answers):
        v.append(round(values[a].count(i)/total_answers*100,2))
        a += 1

      c = 'darkgrey'
      if i == 1:
        c = 'mediumseagreen'
      elif i == 2:
        c = 'mediumorchid'
      elif i == 3:
        c = 'darkgrey'
      elif i == 4:
        c = 'lightgrey'

      fig.add_trace(go.Bar(
          y=answers,
          x=v,
          text=v,
          name=variants[i],
          orientation='h',
          marker=dict(color=c)
      ))

      i += 1

    height = 200 + len(answers)*50
    fig.update_layout(barmode='stack', autosize=False, width=1000, height=height, legend={'traceorder':'normal'})
  else:
    # Draw a simple chart
    question_title = question
    if question == 'Q20':
      question_title = 'Preferred method for packaging Kubernetes applications (Q20)'
    elif question == 'Q43':
      question_title = 'Tools your organisation use to manage its CI/CD pipeline? (Q43)'

    fig = go.Figure(
      data=[go.Bar(x=answers, y=values)],
      layout_title_text='CNCF Annual Survey 2022 data: ' + question_title
    )

  yshift = -50
  if question == 'Q20':
    yshift = -150
  elif question == 'Q43':
    yshift = -120
  fig.add_annotation(
    showarrow=False,
    text='Based on ' + str(total_answers) + ' respondents. Compiled by Palark for https://blog.palark.com/',
    font=dict(size=10),
    xref='x domain', x=0.5, yref='y domain', y=0, yshift=yshift
  )
  fig.show()

# Generate this question's answers data for a chart and draw it
def process_answers(question, answers, multiple, variants):
  column = get_question_col(question)

  # For how many columns we will collect data
  columns_range = 1
  if multiple:
    columns_range = len(answers) - 1

  values = []

  # Define the default votes for each answer
  i = len(answers) - 1
  while i >= 0:
    if variants:
      # If multiple answer variants, make a list of lists
      values.append([])
    else:
      # otherwise, a simple zero for each possible answer
      values.append(0)
    i -= 1

  # Collect votes for each answer from the file
  total = []
  line_num = 0
  for line in results:
    line_num += 1

##    print('line ',line_num,' ',len(line))

    if line_num == 0:
      print('Processing question', line[column])
      continue

    # Skip all rows with descriptions
    if line_num <= 3:
      continue

    # Skip all disqualified answers:
    # - Q2 (col #7) is not "a real person"
    # - Q5 (col #10) is "not employed" or "not sure"
    # - Q7 (col #30) is "teacher/student"
    # - Q13 (col #39) is empty
    if (line[7] and int(line[7]) != 2) or (line[10] and (int(line[10]) == 9 or int(line[10]) == 10)) or (line[30] and int(line[30]) == 9) or (not line[39]):
##      print('Skipping!', line[7], line[10], line[30], line[39])
      continue

    # Get the data from this column only (regular choice)
    # or go through a range of the next columns (multiple choice)
    current_column = column
    current_columns_range = columns_range
    while current_columns_range > 0:

##      print('> Processing column', current_column)

      # There was a vote here, we need to process this answer
      if line[current_column]:

        # Add RDS as a unique responder ID to the total array
        total.append(line[0])

        # Get answer value
        value = int(line[current_column])

        # Save an answer, add it to the array if multiple answer variants
        if variants:
          values[current_column - column + 1].append(value)
        # Or iterate a vote number for this answer
        else:
          values[value] += 1

      # Iterate through the next columns if needed
      current_column += 1
      current_columns_range -= 1

  # Get total respondents for this question
  total_answers = len(np.unique(np.array(total)))

  # Add resulting votes' percentage to each title
  i = 0
  if not variants:
    while i < len(answers):
      answers[i] = str(answers[i]) +' (' + str(round((values[i]/total_answers*100),2)) + '%)'
      i += 1

  print(answers)
##  print(values)

  # We don't need the first (empty) answer in case of multiple choice of answers
  if multiple:
    answers.pop(0)
    values.pop(0)

  return question, answers, values, variants, total_answers


# Make charts for all questions we need

# Q20 is "What is your preferred method for packaging Kubernetes applications? (select one)"
question_title = 'Q20'
# Q20 answers are:
answer_titles = ['—', 'Helm', 'Kustomize', 'Managed Kubernetes offering', 'Buildpacks', 'Porter', 'CNAB', 'Other (please specify)']
# All answers are in this column only
answer_multiple = False

question, answers, values, variants, total_answers = process_answers(question_title, answer_titles, answer_multiple, [])
draw_chart_for_answers(question, answers, values, variants, total_answers)


# Q43 is "What tools does your organization currently use to manage its CI/CD pipeline? (check all that apply)"
question_title = 'Q43'
# Q43 options are:
answer_titles = ['—', 'Akuity', 'Argo', 'AWS CodePipeline', 'Azure Pipelines', 'Bamboo', 'Brigade', 'Buildkite', 'Bunnyshell', 'Cartographer', 'CircleCI', 'Cloudbees Codeship', 'Codefresh', 'Concourse', 'D2iQ Dispatch', 'DolphinScheduler', 'Drone', 'Flagger', 'Flux', 'GitHub Actions', 'GitLab', 'Google Cloud Build', 'Harness.io', 'Jenkins', 'JenkinsX', 'Keptn', 'Octopus Deploy', 'OpenGitOps', 'OpenKruise', 'Ortelius', 'Spacelift', 'Spinnaker', 'TeamCity', 'Tekton Pipelines', 'Travis CI', 'Woodpecker CI', 'XL Deploy', 'Other (please specify)']
# We need answers from the next columns as well
answer_multiple = True

question, answers, values, variants, total_answers = process_answers(question_title, answer_titles, answer_multiple, [])
draw_chart_for_answers(question, answers, values, variants, total_answers)


# Q23 is "Please indicate whether your organization is using in production or evaluating the following graduated CNCF projects"
question_title = 'Q23'
# Q23 options are:
answer_titles = ['—', 'containerd', 'CoreDNS', 'Envoy', 'etcd', 'Fluentd', 'Harbor', 'Helm', 'Jaeger', 'Kubernetes', 'Linkerd', 'Open Policy Agent (OPA)', 'Prometheus', 'Rook', 'The Update Framework (TUF)', 'TiKV', 'Vitess']
# We need answers from the next columns as well
# (we will go through as much next columns as we have titles in the array above)
answer_multiple = True
# Answer in each column can have one of these values
answer_variants = [0, 'Using in production', 'Evaluating', 'Not using', 'Don\'t know or not sure']

question1, answers1, values1, variants, total_answers = process_answers(question_title, answer_titles, answer_multiple, answer_variants)


# Q24 is "Please indicate if your company/organization is evaluating, or currently using in production, any of these incubating CNCF projects"
question_title = 'Q24'
# Q24 options are:
answer_titles = ['—', 'Argo', 'Backstage', 'Buildpacks', 'Chaos Mesh', 'Cilium', 'CloudEvents', 'Container Network Interface (CNI)', 'Contour', 'Cortex', 'CRI-O', 'Crossplane', 'CubeFS', 'Dapr', 'Dragonfly', 'Emissary-Ingress', 'Falco', 'Flux', 'gRPC', 'in-toto', 'Keda', 'Keptn', 'Knative', 'KubeEdge', 'KubeVirt', 'Litmus', 'Longhorn', 'NATS', 'Notary', 'OpenMetrics', 'OpenTelemetry', 'Operator Framework', 'SPIFFE', 'SPIRE', 'Thanos', 'Volcano']
# We need answers from the next columns as well
answer_multiple = True
# Answer in each column can have one of these values
answer_variants = [0, 'Using in production', 'Evaluating', 'Not using', 'Don\'t know or not sure']

question2, answers2, values2, variants, total_answers = process_answers(question_title, answer_titles, answer_multiple, answer_variants)


all_answers = answers1
all_answers.extend(answers2)
all_values = values1
all_values.extend(values2)

charts_categories = {}
charts_categories['Networking'] = ['Cilium', 'Container Network Interface (CNI)', 'Contour', 'CoreDNS', 'Emissary-Ingress', 'Envoy', 'Linkerd']
charts_categories['Streaming, serverless, IoT'] = ['CloudEvents', 'gRPC', 'NATS', 'Knative', 'KubeEdge']
charts_categories['Build, dev, CI/CD'] = ['Argo', 'Backstage', 'Buildpacks', 'Dapr', 'Flux', 'Helm', 'Keptn']
charts_categories['Container runtime'] = ['containerd', 'CRI-O']
charts_categories['Container registry'] = ['Dragonfly', 'Harbor']
charts_categories['K8s extensions & orchestration'] = ['Crossplane', 'Keda', 'Kubernetes', 'KubeVirt', 'Operator Framework', 'Volcano']
charts_categories['Observability'] = ['Cortex', 'Fluentd', 'Jaeger', 'OpenMetrics', 'OpenTelemetry', 'Prometheus', 'Thanos']
charts_categories['Storage'] = ['CubeFS', 'etcd', 'Longhorn', 'Rook', 'TiKV', 'Vitess']
charts_categories['Chaos engineering'] = ['Chaos Mesh', 'Litmus']
charts_categories['Security'] = ['Falco', 'in-toto', 'Kyverno', 'Notary', 'Open Policy Agent (OPA)', 'SPIFFE', 'SPIRE', 'The Update Framework (TUF)']

for category in charts_categories:
  cat_answers = []
  cat_values = []
  cat_variants = variants
  cat_total_answers = total_answers

  for project in charts_categories[category]:
    i = 0
    while i < len(all_answers):
      if (all_answers[i] == project):
        cat_answers.append(all_answers[i])
        cat_values.append(all_values[i])
      i += 1
##  print(cat_answers)
##  print(cat_values)
  print('Drawing a chart for', category)
  draw_chart_for_answers(category, cat_answers, cat_values, cat_variants, cat_total_answers)
