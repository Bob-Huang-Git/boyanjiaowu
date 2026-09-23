import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import HomeView from '../views/HomeView.vue'
import LoginView from '../views/LoginView.vue'
import ForbiddenView from '../views/ForbiddenView.vue'
import NotFoundView from '../views/NotFoundView.vue'
import StudentsView from '../views/StudentsView.vue'
import StudentDetailView from '../views/StudentDetailView.vue'
import CoursesView from '../views/CoursesView.vue'
import ClassesView from '../views/ClassesView.vue'
import ImportsView from '../views/ImportsView.vue'
import EnrollmentsView from '../views/EnrollmentsView.vue'
import TeachingView from '../views/TeachingView.vue'
import ExamView from '../views/ExamView.vue'
import CertificatesView from '../views/CertificatesView.vue'
import FinanceView from '../views/FinanceView.vue'
import TeacherSettlementView from '../views/TeacherSettlementView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/students', name: 'students', component: StudentsView },
    { path: '/students/:id', name: 'student-detail', component: StudentDetailView },
    { path: '/courses', name: 'courses', component: CoursesView },
    { path: '/enrollments', name: 'enrollments', component: EnrollmentsView },
    { path: '/classes', name: 'classes', component: ClassesView },
    { path: '/classes/:id/teaching', name: 'teaching', component: TeachingView },
    { path: '/exams', name: 'exams', component: ExamView },
    { path: '/certificates', name: 'certificates', component: CertificatesView },
    { path: '/finance', name: 'finance', component: FinanceView },
    { path: '/teacher-settlements', name: 'teacher-settlements', component: TeacherSettlementView },
    { path: '/imports/students', name: 'student-import', component: ImportsView },
    { path: '/login', name: 'login', component: LoginView },
    { path: '/403', name: 'forbidden', component: ForbiddenView },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) await auth.load()
  if (!auth.user && to.name !== 'login') return { name: 'login' }
  if (auth.user && to.name === 'login') return { name: 'home' }
  return true
})
