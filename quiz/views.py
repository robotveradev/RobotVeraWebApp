from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import TemplateView, CreateView, DetailView, ListView, UpdateView
from django.views.generic.edit import BaseUpdateView

from candidateprofile.models import CandidateProfile
from jobboard.mixins import OnlyEmployerMixin, OnlyCandidateMixin
from pipeline.models import Action
from quiz.forms import CategoryForm
from quiz.models import ActionExam, Category, Question, Answer, QuestionKind, ExamPassed, AnswerForVerification


class ActionExamView(OnlyEmployerMixin, ListView):
    template_name = 'quiz/action_exams.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.action = None

    def dispatch(self, request, *args, **kwargs):
        self.action = get_object_or_404(Action,
                                        id=kwargs.get('pk'),
                                        pipeline__vacancy__company__employer=request.role_object)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.action.exam.first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = self.action
        return context


class ActionAddQuestionsView(ListView):
    template_name = 'quiz/add_exam.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.action = None

    def dispatch(self, request, *args, **kwargs):
        self.action = get_object_or_404(Action, id=kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Category.objects.filter(employer=self.request.role_object, parent_category=None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = self.action
        context['selected'] = self.get_seleted_exam_questions()
        return context

    def get_seleted_exam_questions(self):
        exam = self.action.exam.first()
        if exam is not None:
            return [qe.id for qe in exam.questions.all()]
        return []

    def post(self, request, *args, **kwargs):
        action = get_object_or_404(Action, pipeline__vacancy__company__employer=request.role_object,
                                   id=request.POST.get('action'))
        question_ids = request.POST.getlist('questions')
        if question_ids:
            action_exam, _ = ActionExam.objects.get_or_create(action=action)
            action_exam.questions.set(Question.objects.filter(id__in=question_ids))
            action_exam.save()
        else:
            messages.error(request, 'You cannot delete all questions from exam.')
        return redirect('action_exam', pk=action.id)


class CandidateExaminingView(OnlyCandidateMixin, TemplateView):
    template_name = 'quiz/candidate_examining.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.action_exam = None
        self.profile = None
        self.request = None
        self.already_pass_exam = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.already_pass_exam:
            context['exam_passed'] = ExamPassed.objects.filter(profile=self.profile,
                                                               exam=self.action_exam).first()
        else:
            context['profile'] = self.profile
            context['exam'] = self.action_exam
        context['action'] = self.action_exam.action
        return context

    def get(self, request, *args, **kwargs):
        self.profile = get_object_or_404(CandidateProfile, pk=self.request.role_object.profile.id)
        self.action_exam = get_object_or_404(ActionExam, pk=kwargs.get('pk'))
        self.check_candidate()
        return super().get(self, request, *args, **kwargs)

    def check_candidate(self):
        self.already_pass_exam = ExamPassed.objects.filter(profile=self.profile,
                                                           exam=self.action_exam).exists()

    def post(self, request, *args, **kwargs):
        self.process_request(request)
        return HttpResponseRedirect(
            reverse('candidate_examining', kwargs={'pk': self.action_exam.pk}))

    def process_request(self, request):
        self.action_exam = get_object_or_404(ActionExam, pk=request.POST.get('exam_id', None))
        self.profile = get_object_or_404(CandidateProfile, pk=request.POST.get('profile_id', None))
        answers = {key: value[0] if len(value) == 1 else value for key, value in dict(request.POST).items() if
                   key.startswith('question_') and value[0] != ''}
        ExamPassed.objects.create(profile=self.profile, exam=self.action_exam, answers=answers)


class QuizIndexPage(TemplateView):
    template_name = 'quiz/main.html'

    def get_context_data(self, **kwargs):
        context = super(QuizIndexPage, self).get_context_data(**kwargs)
        context['categories'] = Category.objects.filter(employer=self.request.role_object, parent_category=None)
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        return self.render_to_response(context)


class NewCategoryView(CreateView):
    model = Category
    form_class = CategoryForm
    success_url = reverse_lazy('quiz_index')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['employer'] = self.request.role_object
        return kwargs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object = None

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.employer = self.request.role_object
        self.object.save()
        return HttpResponseRedirect(self.get_success_url())


class CategoryView(DetailView):
    model = Category


class NewQuestionView(CreateView):
    model = Question
    fields = ['question_text', 'weight', ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cat = None
        self.object = None
        self.next = None

    def get_success_url(self):
        if '_addanother' in self.request.POST:
            return reverse('new_question', kwargs={'category_id': self.cat.id})
        elif '_addanswers' in self.request.POST:
            return reverse('new_answer', kwargs={'question_id': self.object.id})
        return reverse('category', kwargs={'pk': self.cat.id})

    def dispatch(self, request, *args, **kwargs):
        self.cat = get_object_or_404(Category, id=kwargs.get('category_id'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.category = self.cat
        self.object.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.cat
        return context


class NewAnswerView(CreateView):
    model = Answer
    fields = ['text', 'weight', ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.question = None
        self.object = None
        self.another = False

    def get_context_data(self, **kwargs):
        kwargs['question'] = self.question
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        return reverse('category', kwargs={'pk': self.question.category.id})

    def dispatch(self, request, *args, **kwargs):
        self.question = get_object_or_404(Question, id=kwargs.get('question_id'))
        if '_addanother' in request.POST:
            self.another = True
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.question = self.question
        self.object.save()
        self.set_question_type()
        return HttpResponseRedirect(
            reverse('new_answer', kwargs={'question_id': self.question.id}) if self.another else self.get_success_url())

    def set_question_type(self):
        answers = self.question.answers
        valid_count = answers.filter(weight__gt=0).count()
        all_count = answers.count()
        if all_count == 1:
            if valid_count == 1:
                self.object.question.kind = QuestionKind.objects.get(title='FreeResponseQuestion')
        elif all_count > 1:
            if valid_count == 1:
                self.object.question.kind = QuestionKind.objects.get(title='MultipleChoice')
            elif valid_count > 1:
                self.object.question.kind = QuestionKind.objects.get(title='MultipleResponse')
        self.object.question.save()


class QuestionUpdateKindView(UpdateView):
    model = Question
    fields = ['kind', ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pk = None

    def get_success_url(self):
        return reverse('category', kwargs={'pk': self.pk})

    def post(self, request, *args, **kwargs):
        question_object = get_object_or_404(Question, pk=kwargs.get('pk'))
        self.pk = question_object.category.id
        return super().post(request, *args, **kwargs)


class ExamUpdateGradeView(BaseUpdateView):
    model = ActionExam
    fields = ['passing_grade', ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object = None

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponse(True, status=200)

    def form_invalid(self, form):
        return HttpResponse(False, status=403)


class ProcessAnswerView(View):

    def dispatch(self, request, *args, **kwargs):
        if not self.request.is_ajax():
            return HttpResponse(status=403)
        return super(ProcessAnswerView, self).dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        question = get_object_or_404(Question, pk=request.POST.get('que_id'))
        answer = request.POST.get('ans')
        AnswerForVerification.objects.create(question=question, answer=answer)
        return HttpResponse('ok', status=200)


class ExamResultsView(DetailView):
    model = ExamPassed
